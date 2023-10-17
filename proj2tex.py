'''
Projection to texture script

2023 Sasha Volokh

Install the script into your Maya script directory, then use the following command to run:

import proj2tex
import importlib
importlib.reload(proj2tex)
proj2tex.run()
'''

import maya.cmds as cmds
import maya.utils
import maya.mel
import maya.OpenMayaUI as OpenMayaUI
import maya.OpenMaya as OpenMaya
import os.path
import math
import subprocess
import shutil
import glob
from collections import namedtuple
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

VERSION = '1.6'

DIRECTION_FRONT = 'front'
DIRECTION_BACK = 'back'
DIRECTION_SIDE = 'side'
DIRECTION_TOP = 'top'
DIRECTION_BOTTOM = 'bottom'

VALID_DIRECTIONS = [DIRECTION_FRONT, DIRECTION_BACK, DIRECTION_SIDE, DIRECTION_TOP, DIRECTION_BOTTOM]

class Projection:
    def __init__(self, name, direction, image_path):
        self.name = name
        self.direction = direction
        self.image_path = image_path

    def place3dTexture(self):
        return 'place3dTex_{}'.format(self.name)

    def projection(self):
        return 'proj_{}'.format(self.name)

    def file(self):
        return 'projFile_{}'.format(self.name)

    def baked_image_path(self, geom):
        file_format = os.path.splitext(self.image_path)[1][1:]
        return os.path.splitext(self.image_path)[0] + '_baked_{}.{}'.format(geom, file_format)

class Layer:
    def __init__(self, name, color_proj_name, transparency_proj_name):
        self.name = name
        self.color_proj_name = color_proj_name
        self.transparency_proj_name = transparency_proj_name

    def layer_material(self):
        return 'layerMat_{}'.format(self.name)

class Proj2Tex:
    def __init__(self, targets, projections, layers,
                 combined_image_path, projection_padding=0.1, screenshot_res=512, baked_texture_res=(512, 512),
                 fill_texture_seams=True):
        self.targets = targets
        self.projections = projections
        self.layers = layers
        self.combined_image_path = combined_image_path
        self.projection_padding = projection_padding
        self.screenshot_res = screenshot_res
        self.baked_texture_res = baked_texture_res
        self.fill_texture_seams = fill_texture_seams

    def _find_projection_by_name(self, name):
        for proj in self.projections:
            if proj.name == name:
                return proj
        raise Exception('no projection exists with name \'{}\''.format(name))

    def _clear_projections(self):
        for proj in self.projections:
            if cmds.objExists(proj.place3dTexture()):
                cmds.delete(proj.place3dTexture())
            if cmds.objExists(proj.projection()):
                cmds.delete(proj.projection())
            if cmds.objExists(proj.file()):
                cmds.delete(proj.file())

    def _clear_layered_shader(self):
        for l in self.layers:
            if cmds.objExists(l.layer_material()):
                cmds.delete(l.layer_material())
        if cmds.objExists(self._layered_shader()):
            cmds.delete(self._layered_shader())

    def clear_nodes(self):
        self._clear_projections()
        self._clear_layered_shader()
        for geom in self._get_all_target_geometry():
            if cmds.objExists(self._shader(geom)):
                cmds.delete(self._shader(geom))
            if cmds.objExists(self._shader_file(geom)):
                cmds.delete(self._shader_file(geom))

    def _configure_lambert_material(self, mat):
        cmds.setAttr(mat + '.diffuse', 1.0)
        cmds.setAttr(mat + '.translucence', 0.0)
        cmds.setAttr(mat + '.translucenceDepth', 0.0)
        cmds.setAttr(mat + '.translucenceFocus', 0.0)

    @staticmethod
    def is_target_shader(target):
        return cmds.getClassification(cmds.objectType(target), satisfies='shader')

    @staticmethod
    def get_target_geometry(target):
        if Proj2Tex.is_target_shader(target):
            conns = cmds.listConnections(target, d=True, s=False, type='shadingEngine')
            if len(conns) == 0:
                return None
            sg = conns[0]
            for conn in cmds.listConnections(sg):
                cls = cmds.getClassification(cmds.objectType(conn))
                if len(cls) == 1 and 'geometry' in cls[0]:
                    return conn
        else:
            return target

    def _get_all_target_geometry(self):
        geom = set()
        for target in self.targets:
            geom.add(Proj2Tex.get_target_geometry(target))
        return list(geom)

    def compute_bbox(self):
        xmin, ymin, zmin, xmax, ymax, zmax = cmds.exactWorldBoundingBox(self._get_all_target_geometry(), calculateExactly=True)
        padding = self.projection_padding*math.sqrt((xmax - xmin)**2 + (ymax - ymin)**2 + (zmax - zmin)**2)
        xc, yc, zc = (xmin + xmax)/2.0, (ymin + ymax)/2.0, (zmin + zmax)/2.0
        extX, extY, extZ = (xmax - xmin)/2.0, (ymax - ymin)/2.0, (zmax - zmin)/2.0
        return xc - extX - padding, yc - extY - padding, zc - extZ - padding, \
               xc + extX + padding, yc + extY + padding, zc + extZ + padding

    @staticmethod
    def convert_to_cm(val):
        return float(cmds.convertUnit(val, fromUnit=cmds.currentUnit(q=True, linear=True), toUnit='cm').replace('cm', ''))    

    def make_projections(self):
        self.clear_nodes()
        xmin, ymin, zmin, xmax, ymax, zmax = self.compute_bbox()
        for proj in self.projections:
            cmds.shadingNode('place3dTexture', name=proj.place3dTexture(), asUtility=True)
            posX, posY, posZ = (xmin + xmax)/2, (ymin + ymax)/2, (zmin + zmax)/2
            extX, extY, extZ = (xmax - xmin)/2, (ymax - ymin)/2, (zmax - zmin)/2

            # projection will always be created as 2cm x 2cm regardless of current measurement size, so first convert scale to cm
            if proj.direction == DIRECTION_FRONT:
                posZ += extZ
                rotX, rotY, rotZ = 0.0, 0.0, 0.0
                sclX, sclY, sclZ = Proj2Tex.convert_to_cm(extX), Proj2Tex.convert_to_cm(extY), 1.0
            elif proj.direction == DIRECTION_BACK:
                posZ -= extZ
                rotX, rotY, rotZ = 0.0, 180.0, 0.0
                sclX, sclY, sclZ = Proj2Tex.convert_to_cm(extX), Proj2Tex.convert_to_cm(extY), 1.0
            elif proj.direction == DIRECTION_SIDE:
                posX += extX
                rotX, rotY, rotZ = 0.0, 90.0, 0.0
                sclX, sclY, sclZ = Proj2Tex.convert_to_cm(extZ), Proj2Tex.convert_to_cm(extY), 1.0
            elif proj.direction == DIRECTION_TOP:
                posY += extY
                rotX, rotY, rotZ = -90.0, 0.0, 0.0
                sclX, sclY, sclZ = Proj2Tex.convert_to_cm(extX), Proj2Tex.convert_to_cm(extZ), 1.0
            elif proj.direction == DIRECTION_BOTTOM:
                posY -= extY
                rotX, rotY, rotZ = 90.0, 0.0, 0.0
                sclX, sclY, sclZ = Proj2Tex.convert_to_cm(extX), Proj2Tex.convert_to_cm(extZ), 1.0
            else:
                raise Exception(
                    'unrecognized projection direction \'{}\', valid options are {}'.format(proj.direction, VALID_DIRECTIONS))
            
            cmds.setAttr(proj.place3dTexture() + '.translateX', posX)
            cmds.setAttr(proj.place3dTexture() + '.translateY', posY)
            cmds.setAttr(proj.place3dTexture() + '.translateZ', posZ)
            cmds.setAttr(proj.place3dTexture() + '.rotateX', rotX)
            cmds.setAttr(proj.place3dTexture() + '.rotateY', rotY)
            cmds.setAttr(proj.place3dTexture() + '.rotateZ', rotZ)
            cmds.setAttr(proj.place3dTexture() + '.scaleX', sclX) 
            cmds.setAttr(proj.place3dTexture() + '.scaleY', sclY)
            cmds.setAttr(proj.place3dTexture() + '.scaleZ', sclZ)

            cmds.shadingNode('projection', name=proj.projection(), asUtility=True)
            cmds.connectAttr(proj.place3dTexture() + '.worldInverseMatrix', proj.projection() + '.placementMatrix', f=True)

    @staticmethod
    def _world_to_viewport_pt(view, pt):
        p = OpenMaya.MPoint(Proj2Tex.convert_to_cm(pt[0]), Proj2Tex.convert_to_cm(pt[1]), Proj2Tex.convert_to_cm(pt[2]))
        util_x = OpenMaya.MScriptUtil()
        ptr_x = util_x.asShortPtr()
        util_y = OpenMaya.MScriptUtil()
        ptr_y = util_y.asShortPtr()
        unclipped = view.worldToView(p, ptr_x, ptr_y)
        if unclipped:
            x = util_x.getShort(ptr_x)
            y = util_y.getShort(ptr_y)
            return x, y, True
        else:
            return None, None, False

    @staticmethod
    def _get_max_window_size():
        n = OpenMayaUI.M3dView.numberOf3dViews()
        max_width = 0
        max_height = 0
        for i in range(n):
            view = OpenMayaUI.M3dView()
            OpenMayaUI.M3dView.get3dView(i, view)
            max_width = max(max_width, view.portWidth())
            max_height = max(max_height, view.portHeight())
        return max_width, max_height

    def _find_magick_convert(self):
        try:
            subprocess.run(['magick'])
            return ['magick', 'convert'], dict()
        except FileNotFoundError:
            try:
                subprocess.run(['convert'])
                return ['convert'], dict()
            except FileNotFoundError:
                try:
                    subprocess.run(['/opt/local/bin/convert']) # macports install
                    return ['/opt/local/bin/convert'], dict()
                except FileNotFoundError:
                    try:
                        subprocess.run(['/usr/local/bin/convert']) # homebrew install
                        return ['/usr/local/bin/convert'], dict()
                    except FileNotFoundError:
                        d = os.path.dirname(__file__)
                        def iglob(pattern):
                            def either(c):
                                return '[%s%s]' % (c.lower(), c.upper()) if c.isalpha() else c
                            return glob.glob(''.join(map(either, pattern)))
                        magick_install = list(filter(os.path.isdir, iglob(os.path.join(d, 'imagemagick*'))))
                        if len(magick_install) > 0:
                            env = {
                                'MAGICK_HOME': magick_install[0],
                                'DYLD_LIBRARY_PATH': os.path.join(magick_install[0], 'lib')
                            }
                            return [os.path.join(magick_install[0], 'bin', 'magick'), 'convert'], env
                        else:
                            cmds.confirmDialog(title='Error: Cannot find ImageMagick',
                                    message='A valid ImageMagick could not be found: please download the archive from the website and extract it next to the script.',
                                    button='OK')
                            raise Exception('ImageMagick not found')

    def save_screenshots(self):
        max_window_w, max_window_h = Proj2Tex._get_max_window_size()
        max_res = min(max_window_w, max_window_h)
        window_width = min(max_res, self.screenshot_res)
        window_height = window_width
        xmin, ymin, zmin, xmax, ymax, zmax = self.compute_bbox()
        scr_cam = cmds.camera(name='proj_screenshot_cam', orthographic=True)[0]
        try:
            # construct the window twice in order to address issues when changing the screenshot size
            for i in range(2):
                window = cmds.window('proj_screenshot_window')
                form = cmds.formLayout(parent=window)
                meditor = cmds.modelEditor(parent=form)
                cmds.formLayout(form, edit=True, attachForm=[
                    (meditor, 'top', 0),
                    (meditor, 'left', 0),
                    (meditor, 'bottom', 0),
                    (meditor, 'right', 0)
                ])
                cmds.modelEditor(meditor, edit=True, activeView=True, camera=scr_cam, displayAppearance='wireframe',
                                 headsUpDisplay=False, handles=False, grid=False, manipulators=False, viewSelected=True)
                cmds.showWindow(window)
                cmds.window(window, edit=True, width=window_width, height=window_height)
                if i == 0:
                    cmds.deleteUI(meditor)
                    cmds.deleteUI(window)
            view = OpenMayaUI.M3dView()
            OpenMayaUI.M3dView.getM3dViewFromModelEditor(meditor, view)
            viewWidth = view.portWidth()
            viewHeight = view.portHeight()
            view.refresh(False, True)
            for proj in self.projections:
                cmds.setAttr(scr_cam + '.rotateX', cmds.getAttr(proj.place3dTexture() + '.rotateX'))
                cmds.setAttr(scr_cam + '.rotateY', cmds.getAttr(proj.place3dTexture() + '.rotateY'))
                cmds.setAttr(scr_cam + '.rotateZ', cmds.getAttr(proj.place3dTexture() + '.rotateZ'))

                cmds.select(all=True)
                cmds.modelEditor(meditor, edit=True, removeSelected=True)
                view.refresh(False, True)

                cmds.select(self._get_all_target_geometry())
                cmds.select(proj.place3dTexture(), add=True)
                cmds.modelEditor(meditor, edit=True, addSelected=True)
                cmds.viewFit(scr_cam, fitFactor=0.95)

                cmds.modelEditor(meditor, edit=True, removeSelected=True)
                cmds.select(self._get_all_target_geometry())
                cmds.modelEditor(meditor, edit=True, addSelected=True)
                cmds.select(clear=True)

                cmds.playblast(filename=proj.image_path + '.tmp', startTime=1, endTime=1, viewer=False, format='image',
                               offScreen=True, compression=os.path.splitext(proj.image_path)[1][1:],
                               editorPanelName=meditor, width=self.screenshot_res, height=self.screenshot_res,
                               p=100, forceOverwrite=True)
                tmp_image_path = proj.image_path + '.tmp.0001' + os.path.splitext(proj.image_path)[1]

                view.refresh(False, True)
                if proj.direction == DIRECTION_FRONT:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmin, ymin, (zmin+zmax)/2.0])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmax, ymax, (zmin+zmax)/2.0])
                    assert unclipped
                elif proj.direction == DIRECTION_BACK:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmax, ymin, (zmin+zmax)/2.0])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmin, ymax, (zmin+zmax)/2.0])
                    assert unclipped
                elif proj.direction == DIRECTION_SIDE:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [(xmin+xmax)/2.0, ymin, zmax])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [(xmin+xmax)/2.0, ymax, zmin])
                    assert unclipped
                elif proj.direction == DIRECTION_TOP:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmin, (ymin+ymax)/2.0, zmax])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmax, (ymin+ymax)/2.0, zmin])
                    assert unclipped
                elif proj.direction == DIRECTION_BOTTOM:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmin, (ymin+ymax)/2.0, zmin])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmax, (ymin+ymax)/2.0, zmax])
                    assert unclipped
                else:
                    raise Exception('unrecognized projection direction \'{}'.format(proj.direction) + '\', valid options are: {}'.format(proj.direction, VALID_DIRECTIONS))

                ss_crop_xmin = crop_xmin/viewWidth * self.screenshot_res
                ss_crop_ymin = (viewHeight - crop_ymax - 1)/viewHeight * self.screenshot_res
                ss_crop_xmax = crop_xmax/viewWidth * self.screenshot_res
                ss_crop_ymax = (viewHeight - crop_ymin - 1)/viewHeight * self.screenshot_res

                conv_cmd, magick_env = self._find_magick_convert() 
                subprocess.run(conv_cmd + [tmp_image_path, '-crop',
                                '{}x{}+{}+{}'.format(ss_crop_xmax - ss_crop_xmin, ss_crop_ymax - ss_crop_ymin, ss_crop_xmin, ss_crop_ymin),
                                proj.image_path], env={**os.environ, **magick_env}, check=True)

                try:
                    os.remove(tmp_image_path)
                except:
                    print('Warning: Failed to discard temporary screenshot image: {}'.format(tmp_image_path))

        finally:
            cmds.deleteUI(meditor)
            cmds.deleteUI(window)
            cmds.delete(scr_cam)

    def _layered_shader(self):
        return 'layered_shader{}'.format(hash(frozenset(self._get_all_target_geometry())) % 100000)

    def make_layered_shader(self):
        for proj in self.projections:
            cmds.shadingNode('file', name=proj.file(), asTexture=True, isColorManaged=True)
            cmds.setAttr(proj.file() + '.fileTextureName', proj.image_path, type='string')
            if not os.path.exists(proj.image_path):
                cmds.confirmDialog(title='Error: Projection image not found', message='The image \'{}\' does not exist'.format(proj.image_path), button='OK')
            cmds.connectAttr(proj.file() + '.outColor', proj.projection() + '.image', f=True)
        cmds.shadingNode('layeredShader', name=self._layered_shader(), asShader=True)
        cmds.setAttr(self._layered_shader() + '.compositingFlag', 1)
        for index in range(len(self.layers)):
            l = self.layers[index]
            cmds.shadingNode('lambert', name=l.layer_material(), asShader=True)
            self._configure_lambert_material(l.layer_material())
            color_proj = self._find_projection_by_name(l.color_proj_name)
            cmds.connectAttr(color_proj.projection() + '.outColor', l.layer_material() + '.color', f=True)
            if l.transparency_proj_name is not None:
                transp_proj = self._find_projection_by_name(l.transparency_proj_name)
                cmds.connectAttr(transp_proj.projection() + '.outColor', l.layer_material() + '.transparency', f=True)
            layer_mat = l.layer_material()
            cmds.connectAttr(layer_mat + '.outColor', self._layered_shader() + '.inputs[{}].color'.format(index), f=True)
            cmds.connectAttr(layer_mat + '.outTransparency', self._layered_shader() + '.inputs[{}].transparency'.format(index), f=True)
        for target in self.targets:
            if Proj2Tex.is_target_shader(target):
                cmds.connectAttr('{}.outColor'.format(self._layered_shader()), '{}.color'.format(target))
            else:
                cmds.select(target)
                cmds.hyperShade(assign=self._layered_shader())

    def convert(self):
        self._clear_layered_shader()
        all_geom = self._get_all_target_geometry()
        for proj in self.projections:
            for geom in all_geom:
                file_image_name = proj.baked_image_path(geom)
                file_format = os.path.splitext(file_image_name)[1][1:]
                cmds.convertSolidTx(proj.projection() + '.outColor', geom,
                    antiAlias=False, backgroundMode=1, fillTextureSeams=self.fill_texture_seams, force=True,
                    samplePlane=False, shadows=False, alpha=False, doubleSided=False, componentRange=False,
                    resolutionX=self.baked_texture_res[0], resolutionY=self.baked_texture_res[1],
                    fileFormat=file_format, fileImageName=file_image_name)

    def _combined_image_path(self, geom):
        file_fmt = os.path.splitext(self.combined_image_path)[1][1:]
        return os.path.splitext(self.combined_image_path)[0] + '_{}.{}'.format(geom, file_fmt)

    def combine(self):
        tmp_images = []
        try:
            for geom in self._get_all_target_geometry():
                combined_img_path = self._combined_image_path(geom)
                file_fmt = os.path.splitext(combined_img_path)[1][1:]
                img = self._find_projection_by_name(self.layers[len(self.layers)-1].color_proj_name).baked_image_path(geom)
                for i in range(len(self.layers)-2, -1, -1):
                    l = self.layers[i]
                    color_img = self._find_projection_by_name(l.color_proj_name).baked_image_path(geom)
                    if l.transparency_proj_name is None:
                        img = color_img
                    else:
                        transp_img = self._find_projection_by_name(l.transparency_proj_name).baked_image_path(geom)
                        output_path = os.path.splitext(combined_img_path)[0] + '.tmp{}.'.format(i) + file_fmt
                        conv_cmd, magick_env = self._find_magick_convert()
                        subprocess.run(conv_cmd + ['-composite', color_img, img, transp_img, output_path], check=True, env={**os.environ, **magick_env})
                        tmp_images.append(output_path)
                        img = output_path
                shutil.copy(img, combined_img_path)
        finally:
            for path in tmp_images:
                try:
                    os.remove(path)
                except:
                    print('Warning: Failed to discard temporary image: {}'.format(path))

    def _shader(self, geom):
        return '{}_shader'.format(geom)

    def _shader_file(self, geom):
        return '{}_file'.format(geom)

    def apply_to_shaders(self):
        for geom in self._get_all_target_geometry():
            cmds.shadingNode('file', name=self._shader_file(geom), asTexture=True, isColorManaged=True)
            cmds.setAttr(self._shader_file(geom) + '.fileTextureName', self._combined_image_path(geom), type='string')
            shader_created = False
            for target in self.targets:
                if Proj2Tex.get_target_geometry(target) == geom:
                    if Proj2Tex.is_target_shader(target):
                        tgt_shader = target
                    else:
                        if not shader_created:
                            cmds.shadingNode('lambert', name=self._shader(geom), asShader=True)
                            self._configure_lambert_material(self._shader(geom))
                            shader_created = True
                        tgt_shader = self._shader(geom)
                    cmds.connectAttr(self._shader_file(geom) + '.outColor', tgt_shader + '.color', f=True)
            if shader_created:
                cmds.select(geom)
                cmds.hyperShade(assign=self._shader(geom))
        self._clear_projections()

def parse_config(config_path):
    def abs_path(path):
        return os.path.join(os.path.dirname(config_path), path)
    tree = ET.parse(config_path)
    root = tree.getroot()
    projections = []
    for proj_elem in root.findall('./projections/projection'):
        proj = Projection(proj_elem.find('name').text,
                          proj_elem.find('direction').text,
                          abs_path(proj_elem.find('imagePath').text))
        projections.append(proj)
    layers = []
    for layer_elem in root.findall('./layers/layer'):
        transp = layer_elem.find('transparencyProjectionName')
        layer = Layer(layer_elem.find('name').text,
                      layer_elem.find('colorProjectionName').text,
                      transp.text if transp is not None else None)
        layers.append(layer)
    combined_image_path = abs_path(root.find('./combinedImagePath').text)
    config = dict(
        projections=projections, layers=layers,
        combined_image_path=combined_image_path)
    projection_padding_elem = root.find('./projectionPaddingPercentage')
    screenshot_res_elem = root.find('./screenshotResolution')
    baked_tex_res_elem = root.find('./bakedTextureResolution')
    fill_texture_seams_elem = root.find('./fillTextureSeams')
    config['projection_padding'] = float(projection_padding_elem.text)/100.0
    config['screenshot_res'] = int(screenshot_res_elem.find('./width').text)
    config['baked_texture_res'] = (int(baked_tex_res_elem.find('./width').text), int(baked_tex_res_elem.find('./height').text))
    config['fill_texture_seams'] = fill_texture_seams_elem.text == 'True' if fill_texture_seams_elem is not None else True
    return config

def run():
    window = 'proj2tex_window'
    if cmds.window(window, exists=True):
        cmds.deleteUI(window, window=True)
    cmds.window(window, title='Projection To Texture {}'.format(VERSION), menuBar=True)

    def checkOutputDirectory():
        configPath = getConfigPath()
        if configPath is None:
            cmds.confirmDialog(title='Error: Output directory not specified',
                               message='A valid Output Directory must be specified before this operation can be performed.',
                               button='OK')
            return False
        else:
            return True

    def loadConfigMenuItem(*args):
        if checkOutputDirectory():
            configPath = getConfigPath()
            path = cmds.fileDialog2(fileMode=1, caption="Select Configuration File", fileFilter="*.xml")
            if path is None or len(path) == 0:
                return
            path = os.path.abspath(path[0])
            if os.path.exists(configPath):
                os.remove(configPath)
            shutil.copy(path, configPath)
            loadConfig()

    def saveConfigMenuItem(*args):
        if checkOutputDirectory():
            configPath = getConfigPath()
            savePath = cmds.fileDialog2(fileMode=0, caption='Save Configuration As...', fileFilter='*.xml')
            if savePath is None or len(savePath) == 0:
                return
            savePath = os.path.abspath(savePath[0])
            try:
                generateConfig()
                shutil.copy(configPath, savePath)
            except ConfigGenerationError as e:
                cmds.confirmDialog(title='Saving error', label='Error when saving configuration: {}'.format(e))

    def resetConfigToDefault(*args):
        cmds.deleteUI(window, window=True)
        run()

    fileMenu = cmds.menu(label='File', parent=window)
    cmds.menuItem(label='Load Configuration', parent=fileMenu, command=loadConfigMenuItem)
    cmds.menuItem(label='Save Configuration As...', parent=fileMenu, command=saveConfigMenuItem)
    cmds.menuItem(label='Reset Configuration To Default', parent=fileMenu, command=resetConfigToDefault)

    def openYouTubeTutorial(*args):
        cmds.showHelp('https://www.youtube.com/watch?v=VCAxwzO7qOM', absolute=True)

    def openInstructions(*args):
        cmds.showHelp('https://docs.google.com/document/d/1VQoMDkgJMDK96tKnDrkXo3BrMqFonKYxQL4Dk9eqtLg/edit?usp=sharing', absolute=True)

    def openAbout(*args):
        cmds.confirmDialog(
            title='About',
            message='Projection To Texture Script v{}\nWritten by Sasha Volokh (2023)'.format(VERSION),
            button='OK')

    helpMenu = cmds.menu(label='Help', helpMenu=True, parent=window)
    cmds.menuItem(label='YouTube Tutorial', parent=helpMenu, command=openYouTubeTutorial)
    cmds.menuItem(label='Documentation', parent=helpMenu, command=openInstructions)
    cmds.menuItem(label='About', parent=helpMenu, command=openAbout)

    column = cmds.columnLayout(parent=window, columnWidth=400, columnAttach=('both', 5), rowSpacing=10)

    cmds.text(parent=column, label='Target Meshes or Shaders:')
    row = cmds.rowLayout(parent=column, numberOfColumns=2, columnWidth2=(285, 100), columnAttach2=('both', 'both'))
    targetsTextField = cmds.textField(parent=row)

    def getTargets():
        return list(
            filter(lambda s: len(s) > 0,
                map(lambda s: s.strip(), cmds.textField(targetsTextField, q=True, text=True).split(','))))

    def addSelectedAsTargets(*args):
        sel = cmds.ls(selection=True)
        if len(sel) == 0:
            cmds.confirmDialog(title='Error: No selection', message='No object is currently selected', button='OK')
            return
        targets = getTargets()
        for obj in sel:
            if obj not in targets:
                targets.append(obj)
        cmds.textField(targetsTextField, edit=True, text=', '.join(targets))
    cmds.button(parent=row, label='Add Selected', command=addSelectedAsTargets)

    row = cmds.rowLayout(parent=column, numberOfColumns=3, columnWidth3=(100, 180, 120), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Output Directory:')
    outputDirTextField = cmds.textField(parent=row)
    def browseOutputDir(*args):
        path = cmds.fileDialog2(fileMode=3, caption='Browse Output Directory...')
        if path is None or len(path) == 0:
            return
        path = path[0]
        if not os.path.exists(path):
            cmds.confirmDialog(title='Error: Invalid output directory', message='Specified output directory is not valid or does not exist', button='OK')
            return
        path = os.path.abspath(path)
        cmds.textField(outputDirTextField, edit=True, text=path)
        if os.path.exists(getConfigPath()):
            loadConfig()
            cmds.confirmDialog(title='Loaded Existing Configuration',
                               message='Loaded existing configuration found at {}'.format(getConfigPath()),
                               button='OK')
        for btn in p2tButtons:
            cmds.button(btn, edit=True, enable=True)

    cmds.button(parent=row, label='Browse', command=browseOutputDir)

    configFrame = cmds.frameLayout(parent=column, label='Configuration')
    configScroll = cmds.scrollLayout(parent=configFrame, verticalScrollBarThickness=0, horizontalScrollBarThickness=0, height=250)
    configColumn = cmds.columnLayout(parent=configScroll, columnWidth=300, columnAttach=('both', 5), rowSpacing=10)

    grid = cmds.gridLayout(parent=configColumn, numberOfColumns=3, cellWidth=100)
    cmds.text(parent=grid, label='Projections')
    cmds.text(parent=grid, label='Color')
    cmds.text(parent=grid, label='Alpha')
    frontCheckBox = cmds.checkBox(parent=grid, value=True, label='Front')
    frontColorTextField = cmds.textField(parent=grid, text='front.png')
    frontAlphaTextField = cmds.textField(parent=grid, text='')
    backCheckBox = cmds.checkBox(parent=grid, value=True, label='Back')
    backColorTextField = cmds.textField(parent=grid, text='back.png')
    backAlphaTextField = cmds.textField(parent=grid, text='')
    sideCheckBox = cmds.checkBox(parent=grid, value=True, label='Side')
    sideColorTextField = cmds.textField(parent=grid, text='')
    sideAlphaTextField = cmds.textField(parent=grid, text='sideAlpha.png')
    topCheckBox = cmds.checkBox(parent=grid, value=False, label='Top')
    topColorTextField = cmds.textField(parent=grid, text='')
    topAlphaTextField = cmds.textField(parent=grid, text='')
    bottomCheckBox = cmds.checkBox(parent=grid, value=False, label='Bottom')
    bottomColorTextField = cmds.textField(parent=grid, text='')
    bottomAlphaTextField = cmds.textField(parent=grid, text='')

    ProjControl = namedtuple('ProjControl', ['name', 'direction', 'checkBox', 'colorTextField', 'alphaTextField'])
    projControls = [
        ProjControl('Front', DIRECTION_FRONT, frontCheckBox, frontColorTextField, frontAlphaTextField),
        ProjControl('Back', DIRECTION_BACK, backCheckBox, backColorTextField, backAlphaTextField),
        ProjControl('Side', DIRECTION_SIDE, sideCheckBox, sideColorTextField, sideAlphaTextField),
        ProjControl('Top', DIRECTION_TOP, topCheckBox, topColorTextField, topAlphaTextField),
        ProjControl('Bottom', DIRECTION_BOTTOM, bottomCheckBox, bottomColorTextField, bottomAlphaTextField)
    ]

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=2, columnWidth2=(150, 150), columnAttach2=('both', 'both'))
    cmds.text(parent=row, label='Projection Padding (%):')
    projectionPaddingTextField = cmds.textField(parent=row, text='10')

    LayerControl = namedtuple('LayerControl', ['colorMenu', 'alphaMenu'])

    grid = cmds.gridLayout(parent=configColumn, numberOfColumns=3, cellWidth=95)
    cmds.text(parent=grid, label='Layers')
    cmds.text(parent=grid, label='Color')
    cmds.text(parent=grid, label='Alpha')
    layerControls = []
    maxLayers = 4
    for i in range(maxLayers):
        cmds.text(parent=grid, label='Layer {}'.format(i+1))
        layerColorMenu = cmds.optionMenu(parent=grid)
        cmds.menuItem(label='', parent=layerColorMenu)
        for pc in projControls:
            cmds.menuItem(label=pc.name, parent=layerColorMenu)
        layerAlphaMenu = cmds.optionMenu(parent=grid)
        cmds.menuItem(label='', parent=layerAlphaMenu)
        for pc in projControls:
            cmds.menuItem(label=pc.name, parent=layerAlphaMenu)
        layerControls.append(LayerControl(layerColorMenu, layerAlphaMenu))
    cmds.optionMenu(layerControls[0].colorMenu, edit=True, select=[i for i in range(len(projControls)) if projControls[i].name == 'Front'][0]+2)
    cmds.optionMenu(layerControls[0].alphaMenu, edit=True, select=[i for i in range(len(projControls)) if projControls[i].name == 'Side'][0]+2)
    cmds.optionMenu(layerControls[1].colorMenu, edit=True, select=[i for i in range(len(projControls)) if projControls[i].name == 'Back'][0]+2)

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=2, columnWidth2=(150, 150), columnAttach2=('both', 'both'))
    cmds.text(parent=row, label='Combined Image Name:')
    combinedTextField = cmds.textField(parent=row, text='combined.png')

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=3, columnWidth3=(150, 75, 75), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Screenshot Resolution:')
    screenshotResTextField = cmds.textField(parent=row, text='512')

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=3, columnWidth3=(150, 75, 75), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Converted Resolution:')
    convertedResWidthTextField = cmds.textField(parent=row, text='512')
    convertedResHeightTextField = cmds.textField(parent=row, text='512')

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=2, columnWidth2=(15, 285), columnAttach2=('both', 'both'))
    cmds.text(parent=row, label='')
    fillTextureSeamsCheckbox = cmds.checkBox(parent=row, label='Fill Texture Seams', value=True)

    def getOutputDirectory():
        outdir = cmds.textField(outputDirTextField, q=True, text=True)
        if not os.path.exists(outdir):
            return None
        return os.path.abspath(outdir)

    def getConfigPath():
        outdir = getOutputDirectory()
        if outdir is None:
            return None
        return os.path.join(outdir, 'config.xml')

    def loadConfig():
        outdir = getOutputDirectory()
        configPath = getConfigPath()
        def relativizePath(path):
            return os.path.relpath(os.path.abspath(path), outdir)
        cfg = parse_config(configPath)
        # load projections
        for pc in projControls:
            projPresent = False
            colorProjName = '{}ColorProj'.format(pc.name)
            alphaProjName = '{}AlphaProj'.format(pc.name)
            cmds.textField(pc.colorTextField, edit=True, text='')
            cmds.textField(pc.alphaTextField, edit=True, text='')
            for proj in cfg['projections']:
                if proj.direction == pc.direction:
                    if proj.name == colorProjName:
                        projPresent = True
                        cmds.textField(pc.colorTextField, edit=True, text=relativizePath(proj.image_path))
                    elif proj.name == alphaProjName:
                        projPresent = True
                        cmds.textField(pc.alphaTextField, edit=True, text=relativizePath(proj.image_path))
            cmds.checkBox(pc.checkBox, edit=True, value=projPresent)
        # load layers
        layers = cfg['layers']
        numLayers = len(layers)
        for lc in layerControls:
            cmds.optionMenu(lc.colorMenu, edit=True, select=1)
            cmds.optionMenu(lc.alphaMenu, edit=True, select=1)
        for i in range(numLayers):
            lc = layerControls[i]
            colorProjName = layers[numLayers-i-1].color_proj_name
            colorProjSel = [i for i in range(len(projControls)) if '{}ColorProj'.format(projControls[i].name) == colorProjName][0]+2
            cmds.optionMenu(lc.colorMenu, edit=True, select=colorProjSel)
            if i < numLayers-1:
                alphaProjName = layers[numLayers-i-2].transparency_proj_name
                alphaProjSel = [i for i in range(len(projControls)) if '{}AlphaProj'.format(projControls[i].name) == alphaProjName][0]+2
                cmds.optionMenu(lc.alphaMenu, edit=True, select=alphaProjSel)
        # load remaining settings
        cmds.textField(combinedTextField, edit=True, text=relativizePath(cfg['combined_image_path']))
        cmds.textField(projectionPaddingTextField, edit=True, text=str(cfg['projection_padding']*100.0))
        cmds.textField(screenshotResTextField, edit=True, text=str(cfg['screenshot_res']))
        cmds.textField(convertedResWidthTextField, edit=True, text=str(cfg['baked_texture_res'][0]))
        cmds.textField(convertedResHeightTextField, edit=True, text=str(cfg['baked_texture_res'][1]))
        cmds.checkBox(fillTextureSeamsCheckbox, edit=True, value=cfg['fill_texture_seams'])

    class ConfigGenerationError(Exception):
        pass

    def generateConfig():
        proj2tex = ET.Element('proj2tex')

        projections = ET.SubElement(proj2tex, 'projections')
        for pc in projControls:
            if cmds.checkBox(pc.checkBox, q=True, value=True):
                colorPath = cmds.textField(pc.colorTextField, q=True, text=True).strip()
                if len(colorPath) > 0:
                    proj = ET.SubElement(projections, 'projection')
                    ET.SubElement(proj, 'name').text = '{}ColorProj'.format(pc.name)
                    ET.SubElement(proj, 'direction').text = pc.direction
                    ET.SubElement(proj, 'imagePath').text = colorPath
                alphaPath = cmds.textField(pc.alphaTextField, q=True, text=True).strip()
                if len(alphaPath) > 0:
                    proj = ET.SubElement(projections, 'projection')
                    ET.SubElement(proj, 'name').text = '{}AlphaProj'.format(pc.name)
                    ET.SubElement(proj, 'direction').text = pc.direction
                    ET.SubElement(proj, 'imagePath').text = alphaPath

        layers = ET.SubElement(proj2tex, 'layers')
        activeLayerControls = [lc for lc in layerControls if cmds.optionMenu(lc.colorMenu, q=True, select=True) > 1]
        numLayers = len(activeLayerControls)

        # re-interpret alphas as transparency
        for i in range(numLayers):
            colorProjSel = cmds.optionMenu(activeLayerControls[numLayers-i-1].colorMenu, q=True, select=True)
            colorProjControls = projControls[colorProjSel-2]
            colorProjName = '{}ColorProj'.format(colorProjControls.name)
            if not cmds.checkBox(colorProjControls.checkBox, q=True, value=True) or len(cmds.textField(colorProjControls.colorTextField, q=True, text=True).strip()) == 0:
                raise ConfigGenerationError('Layer {} refers to a non-existent color projection'.format(numLayers-i))
            if i < numLayers - 1:
                alphaProjSel = cmds.optionMenu(activeLayerControls[numLayers-i-2].alphaMenu, q=True, select=True)
                if alphaProjSel <= 1:
                    raise ConfigGenerationError('All layers, except for the last layer, must have alpha defined')
                alphaProjControls = projControls[alphaProjSel-2]
                if not cmds.checkBox(alphaProjControls.checkBox, q=True, value=True) or len(cmds.textField(alphaProjControls.alphaTextField, q=True, text=True).strip()) == 0:
                    raise ConfigGenerationError('Layer {} refers to a non-existent alpha projection'.format(numLayers-i-1))
                alphaProjName = '{}AlphaProj'.format(alphaProjControls.name)
            else:
                alphaProjName = None
            layer = ET.SubElement(layers, 'layer')
            ET.SubElement(layer, 'name').text = 'Layer{}'.format(i+1)
            ET.SubElement(layer, 'colorProjectionName').text = colorProjName
            if alphaProjName is not None:
                ET.SubElement(layer, 'transparencyProjectionName').text = alphaProjName

        ET.SubElement(proj2tex, 'combinedImagePath').text = cmds.textField(combinedTextField, q=True, text=True)

        ET.SubElement(proj2tex, 'projectionPaddingPercentage').text = str(float(cmds.textField(projectionPaddingTextField, q=True, text=True).strip()))

        screenshotResolution = ET.SubElement(proj2tex, 'screenshotResolution')
        ET.SubElement(screenshotResolution, 'width').text = str(int(cmds.textField(screenshotResTextField, q=True, text=True).strip()))
        ET.SubElement(screenshotResolution, 'height').text = str(int(cmds.textField(screenshotResTextField, q=True, text=True).strip()))

        bakedTextureResolution = ET.SubElement(proj2tex, 'bakedTextureResolution')
        ET.SubElement(bakedTextureResolution, 'width').text = str(int(cmds.textField(convertedResWidthTextField, q=True, text=True).strip()))
        ET.SubElement(bakedTextureResolution, 'height').text = str(int(cmds.textField(convertedResHeightTextField, q=True, text=True).strip()))

        ET.SubElement(proj2tex, 'fillTextureSeams').text = str(cmds.checkBox(fillTextureSeamsCheckbox, q=True, value=True))

        s = ET.tostring(proj2tex, 'utf-8')
        with open(getConfigPath(), 'w') as f:
            f.write(minidom.parseString(s).toprettyxml(indent='\t'))


    def makeP2T():
        targets = set(getTargets())
        if len(targets) == 0:
            cmds.confirmDialog(title='Error: Invalid target', message='At least one target must be specified', button='OK')
            return None
        for tgt in targets:
            if not cmds.objExists(tgt):
                cmds.confirmDialog(title='Error: Invalid target', message='Specified target \'{}\' does not exist'.format(tgt), button='OK')
                return None
            if Proj2Tex.get_target_geometry(tgt) is None:
                cmds.confirmDialog(title='Error: Shader not associated with geometry', message='Target shader \'{}\' is not currently assigned to any object'.format(tgt), button='OK')
                return None
        if getOutputDirectory() is None:
            cmds.confirmDialog(title='Error: Invalid output directory', message='Invalid output directory specified', button='OK')
            return None
        try:
            generateConfig()
        except ConfigGenerationError as e:
            cmds.confirmDialog(title='Error: Invalid configuration', message='Configuration is invalid: {}'.format(e), button='OK')
            return None
        configPath = getConfigPath()
        assert configPath is not None
        assert os.path.exists(configPath)
        return Proj2Tex(targets, **parse_config(configPath))

    def makeProjections(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.make_projections()

    def saveScreenshots(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.save_screenshots()

    def makeLayeredShader(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.make_layered_shader()

    def convert(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.convert()

    def combine(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.combine()

    def applyToShaders(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.apply_to_shaders()

    def reset(*args):
        p2t = makeP2T()
        if p2t is not None:
            p2t.clear_nodes()

    p2tButtons = [
        cmds.button(parent=column, label='1. Make Projections', command=makeProjections),
        cmds.button(parent=column, label='2. Save Screenshots', command=saveScreenshots),
        cmds.button(parent=column, label='3. Make Layered Shader', command=makeLayeredShader),
        cmds.button(parent=column, label='4. Convert Projections To Textures', command=convert),
        cmds.button(parent=column, label='5. Combine Textures', command=combine),
        cmds.button(parent=column, label='6. Apply To Shaders', command=applyToShaders),
        cmds.button(parent=column, label='Reset', command=reset)
    ]
    for btn in p2tButtons:
        cmds.button(btn, edit=True, enable=False)

    cmds.showWindow(window)
    cmds.window(window, edit=True, width=400, height=650, sizeable=False)
