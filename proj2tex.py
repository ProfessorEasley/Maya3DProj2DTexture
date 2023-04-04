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
import xml.etree.ElementTree as ET

from typing import Optional

VERSION = '1.0'

DIRECTION_FRONT = 'front'
DIRECTION_BACK = 'back'
DIRECTION_SIDE = 'side'
VALID_DIRECTIONS = [DIRECTION_FRONT, DIRECTION_BACK, DIRECTION_SIDE]

class Projection:
    def __init__(self, name: str, direction: str, image_path: str):
        self.name = name
        self.direction = direction
        self.image_path = image_path

    def place3dTexture(self):
        return 'place3dTex_{}'.format(self.name)

    def projection(self):
        return 'proj_{}'.format(self.name)

    def file(self):
        return 'projFile_{}'.format(self.name)

    def baked_image_path(self):
        file_format = os.path.splitext(self.image_path)[1][1:]
        return os.path.splitext(self.image_path)[0] + '_baked.{}'.format(file_format)

class Layer:
    def __init__(self, name: str, color_proj_name: str, transparency_proj_name: Optional[str]):
        self.name = name
        self.color_proj_name = color_proj_name
        self.transparency_proj_name = transparency_proj_name

    def layer_material(self):
        return 'layerMat_{}'.format(self.name)

class Proj2Tex:
    def __init__(self, target_mesh: str, projections: list[Projection], layers: list[Layer],
                 combined_image_path: str, projection_padding=0.1, screenshot_res=(1280, 720), baked_texture_res=(512, 512)):
        self.target_mesh = target_mesh
        self.projections = projections
        self.layers = layers
        self.combined_image_path = combined_image_path
        self.projection_padding = projection_padding
        self.screenshot_res = screenshot_res
        self.baked_texture_res = baked_texture_res

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
        if cmds.objExists(self._single_shader()):
            cmds.delete(self._single_shader())
        if cmds.objExists(self._single_shader_file()):
            cmds.delete(self._single_shader_file())

    def _configure_lambert_material(self, mat):
        cmds.setAttr(mat + '.diffuse', 1.0)
        cmds.setAttr(mat + '.translucence', 0.0)
        cmds.setAttr(mat + '.translucenceDepth', 0.0)
        cmds.setAttr(mat + '.translucenceFocus', 0.0)

    def compute_bbox(self):
        xmin, ymin, zmin, xmax, ymax, zmax = cmds.exactWorldBoundingBox(self.target_mesh, calculateExactly=True)
        padding = self.projection_padding*math.sqrt((xmax - xmin)**2 + (ymax - ymin)**2 + (zmax - zmin)**2)
        xc, yc, zc = (xmin + xmax)/2.0, (ymin + ymax)/2.0, (zmin + zmax)/2.0
        extX, extY, extZ = (xmax - xmin)/2.0, (ymax - ymin)/2.0, (zmax - zmin)/2.0
        return xc - extX - padding, yc - extY - padding, zc - extZ - padding, \
               xc + extX + padding, yc + extY + padding, zc + extZ + padding

    def make_projections(self):
        self.clear_nodes()
        xmin, ymin, zmin, xmax, ymax, zmax = self.compute_bbox()
        for proj in self.projections:
            cmds.shadingNode('place3dTexture', name=proj.place3dTexture(), asUtility=True)
            posX, posY, posZ = (xmin + xmax)/2, (ymin + ymax)/2, (zmin + zmax)/2
            extX, extY, extZ = (xmax - xmin)/2, (ymax - ymin)/2, (zmax - zmin)/2
            if proj.direction == DIRECTION_FRONT:
                posZ += extZ
                rotX, rotY, rotZ = 0.0, 0.0, 0.0
                sclX, sclY, sclZ = extX, extY, 0.0
            elif proj.direction == DIRECTION_BACK:
                posZ -= extZ
                rotX, rotY, rotZ = 0.0, 180.0, 0.0
                sclX, sclY, sclZ = extX, extY, 0.0
            elif proj.direction == DIRECTION_SIDE:
                posX += extX
                rotX, rotY, rotZ = 0.0, 90.0, 0.0
                sclX, sclY, sclZ = extZ, extY, 1.0
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
        p = OpenMaya.MPoint(pt[0], pt[1], pt[2])
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

    def save_screenshots(self):
        xmin, ymin, zmin, xmax, ymax, zmax = self.compute_bbox()
        scr_cam = cmds.camera(name='proj_screenshot_cam', orthographic=True)[0]
        window = cmds.window('proj_screenshot_window')
        form = cmds.formLayout()
        meditor = cmds.modelEditor()
        try:
            cmds.formLayout(form, edit=True, attachForm=[
                (meditor, 'top', 0),
                (meditor, 'left', 0),
                (meditor, 'bottom', 0),
                (meditor, 'right', 0)
            ])
            cmds.showWindow(window)
            cmds.window(window, edit=True, width=self.screenshot_res[0], height=self.screenshot_res[1])
            cmds.modelEditor(meditor, edit=True, activeView=True, camera=scr_cam, displayAppearance='wireframe',
                             headsUpDisplay=False, handles=False, grid=False, manipulators=False, viewSelected=True)
            view = OpenMayaUI.M3dView()
            OpenMayaUI.M3dView.getM3dViewFromModelEditor(meditor, view)
            viewWidth = view.portWidth()
            viewHeight = view.portHeight()
            for proj in self.projections:
                cmds.setAttr(scr_cam + '.rotateX', cmds.getAttr(proj.place3dTexture() + '.rotateX'))
                cmds.setAttr(scr_cam + '.rotateY', cmds.getAttr(proj.place3dTexture() + '.rotateY'))
                cmds.setAttr(scr_cam + '.rotateZ', cmds.getAttr(proj.place3dTexture() + '.rotateZ'))

                cmds.select(all=True)
                cmds.modelEditor(meditor, edit=True, removeSelected=True)

                cmds.select(self.target_mesh)
                cmds.select(proj.place3dTexture(), add=True)
                cmds.modelEditor(meditor, edit=True, addSelected=True)
                cmds.viewFit(scr_cam, fitFactor=0.95)

                cmds.select(self.target_mesh)

                view.refresh(False, True)
                if proj.direction == DIRECTION_FRONT:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmin, ymin, (zmin+zmax)/2.0])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmax, ymax, (zmin+zmax)/2.0])
                    assert unclipped
                elif proj.direction == DIRECTION_SIDE:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [(xmin+xmax)/2.0, ymin, zmax])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [(xmin+xmax)/2.0, ymax, zmin])
                    assert unclipped
                elif proj.direction == DIRECTION_BACK:
                    crop_xmin, crop_ymin, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmax, ymin, (zmin+zmax)/2.0])
                    assert unclipped
                    crop_xmax, crop_ymax, unclipped = Proj2Tex._world_to_viewport_pt(view, [xmin, ymax, (zmin+zmax)/2.0])
                    assert unclipped
                else:
                    raise Exception('unrecognized projection direction \'{}'.format(proj.direction) + '\', valid options are: {}'.format(proj.direction, VALID_DIRECTIONS))

                tmp_image_path = proj.image_path + '.tmp' + os.path.splitext(proj.image_path)[1]
                cmds.refresh(fileExtension='png', filename=tmp_image_path)

                ss_crop_xmin = crop_xmin
                ss_crop_ymin = viewHeight - crop_ymax - 1
                ss_crop_xmax = crop_xmax
                ss_crop_ymax = viewHeight - crop_ymin - 1

                subprocess.run(['magick', 'convert', tmp_image_path, '-crop',
                                '{}x{}+{}+{}'.format(ss_crop_xmax - ss_crop_xmin, ss_crop_ymax - ss_crop_ymin, ss_crop_xmin, ss_crop_ymin),
                                proj.image_path])

                os.remove(tmp_image_path)

        finally:
            cmds.deleteUI(meditor)
            cmds.deleteUI(window)
            cmds.delete(scr_cam)

    def _layered_shader(self):
        return '{}_layered_material'.format(self.target_mesh)

    def _single_shader(self):
        return '{}_material'.format(self.target_mesh)

    def _single_shader_file(self):
        return '{}_file'.format(self.target_mesh)

    def make_layered_shader(self):
        for proj in self.projections:
            cmds.shadingNode('file', name=proj.file(), asTexture=True, isColorManaged=True)
            cmds.setAttr(proj.file() + '.fileTextureName', proj.image_path, type='string')
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
        cmds.select(self.target_mesh)
        cmds.hyperShade(assign=self._layered_shader())

    def convert(self):
        self._clear_layered_shader()
        for proj in self.projections:
            file_image_name = proj.baked_image_path()
            file_format = os.path.splitext(file_image_name)[1][1:]
            cmds.convertSolidTx(proj.projection() + '.outColor', self.target_mesh,
                antiAlias=False, backgroundMode=1, fillTextureSeams=True, force=True,
                samplePlane=False, shadows=False, alpha=False, doubleSided=False, componentRange=False,
                resolutionX=self.baked_texture_res[0], resolutionY=self.baked_texture_res[1],
                fileFormat=file_format, fileImageName=file_image_name)

    def combine(self):
        tmp_images = []
        try:
            file_fmt = os.path.splitext(self.combined_image_path)[1][1:]
            img = self._find_projection_by_name(self.layers[len(self.layers)-1].color_proj_name).baked_image_path()
            for i in range(len(self.layers)-2, -1, -1):
                l = self.layers[i]
                color_img = self._find_projection_by_name(l.color_proj_name).baked_image_path()
                if l.transparency_proj_name is None:
                    img = color_img
                else:
                    transp_img = self._find_projection_by_name(l.transparency_proj_name).baked_image_path()
                    output_path = os.path.splitext(self.combined_image_path)[0] + '.tmp{}.'.format(i) + file_fmt
                    subprocess.run(['magick', 'convert', '-composite', color_img, img, transp_img, output_path])
                    tmp_images.append(output_path)
                    img = output_path
            shutil.copy(img, self.combined_image_path)
        finally:
            for path in tmp_images:
                os.remove(path)

    def apply_to_single_shader(self):
        cmds.shadingNode('lambert', name=self._single_shader(), asShader=True)
        self._configure_lambert_material(self._single_shader())
        cmds.shadingNode('file', name=self._single_shader_file(), asTexture=True, isColorManaged=True)
        cmds.setAttr(self._single_shader_file() + '.fileTextureName', self.combined_image_path, type='string')
        cmds.connectAttr(self._single_shader_file() + '.outColor', self._single_shader() + '.color', f=True)
        cmds.select(self.target_mesh)
        cmds.hyperShade(assign=self._single_shader())
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
    if projection_padding_elem is not None:
        config['projection_padding'] = float(projection_padding_elem.text)/100.0
    if screenshot_res_elem is not None:
        config['screenshot_res'] = (int(screenshot_res_elem.find('./width').text), int(screenshot_res_elem.find('./height').text))
    if baked_tex_res_elem is not None:
        config['baked_texture_res'] = (int(baked_tex_res_elem.find('./width').text), int(baked_tex_res_elem.find('./height').text))
    return config

def run():
    window = 'proj2tex_window'
    if cmds.window(window, exists=True):
        cmds.deleteUI(window, window=True)
    cmds.window(window, title='Projection To Texture {}'.format(VERSION), menuBar=True)

    def openInstructions(*args):
        cmds.showHelp('https://docs.google.com/document/d/1VQoMDkgJMDK96tKnDrkXo3BrMqFonKYxQL4Dk9eqtLg/edit?usp=sharing', absolute=True)

    def openAbout(*args):
        cmds.confirmDialog(
            title = 'About',
            message = 'Projection To Texture Script v{}\nWritten by Sasha Volokh (2023)'.format(VERSION),
            button = 'OK')

    helpMenu = cmds.menu(label='Help', helpMenu=True, parent=window)
    cmds.menuItem(label='Instructions', parent=helpMenu, command=openInstructions)
    cmds.menuItem(label='About', parent=helpMenu, command=openAbout)

    column = cmds.columnLayout(parent=window, columnWidth=400, columnAttach=('both', 5), rowSpacing=10)

    row = cmds.rowLayout(parent=column, numberOfColumns=3, columnWidth3=(100, 180, 120), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Target Mesh:')
    targetMeshTextField = cmds.textField(parent=row)
    def updateTargetMesh(*args):
        sel = cmds.ls(selection=True)
        if len(sel) == 0:
            cmds.confirmDialog(title='Error: No selection', message='No object is currently selected', button='OK')
            return
        elif len(sel) > 1:
            cmds.confirmDialog(title='Error: Ambiguous selection', message='More than one object selected (only the target mesh should be selected)', button='OK')
            return
        cmds.textField(targetMeshTextField, edit=True, text=sel[0])
    cmds.button(parent=row, label='Update', command=updateTargetMesh)

    row = cmds.rowLayout(parent=column, numberOfColumns=3, columnWidth3=(100, 180, 120), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Working Directory:')
    workingDirTextField = cmds.textField(parent=row)
    def browseWorkingDir(*args):
        # TODO
        pass
    cmds.button(parent=row, label='Browse', command=browseWorkingDir)

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

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=2, columnWidth2=(150, 150), columnAttach2=('both', 'both'))
    cmds.text(parent=row, label='Projection Padding (%):')
    cmds.textField(parent=row, text='10')

    grid = cmds.gridLayout(parent=configColumn, numberOfColumns=3, cellWidth=95)
    cmds.text(parent=grid, label='Layers')
    cmds.text(parent=grid, label='Color')
    cmds.text(parent=grid, label='Alpha')
    layerControls = []
    maxLayers = 4
    for i in range(maxLayers):
        cmds.text(parent=grid, label='Layer {}'.format(i+1))
        layerColorMenu = cmds.optionMenu(parent=grid)
        cmds.menuItem(label='')
        cmds.menuItem(label='Front')
        cmds.menuItem(label='Back')
        cmds.menuItem(label='Side')
        layerAlphaMenu = cmds.optionMenu(parent=grid)
        cmds.menuItem(label='')
        cmds.menuItem(label='Front')
        cmds.menuItem(label='Back')
        cmds.menuItem(label='Side')
        layerControls.append((layerColorMenu, layerAlphaMenu))
    cmds.optionMenu(layerControls[0][0], edit=True, select=2)
    cmds.optionMenu(layerControls[0][1], edit=True, select=4)
    cmds.optionMenu(layerControls[1][0], edit=True, select=3)

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=2, columnWidth2=(150, 150), columnAttach2=('both', 'both'))
    cmds.text(parent=row, label='Combined Image Name:')
    combinedTextField = cmds.textField(parent=row, text='combined.png')

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=3, columnWidth3=(150, 75, 75), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Screenshot Resolution:')
    screenshotResWidthTextField = cmds.textField(parent=row, text='1280')
    screenshotResHeightTextField = cmds.textField(parent=row, text='720')

    row = cmds.rowLayout(parent=configColumn, numberOfColumns=3, columnWidth3=(150, 75, 75), columnAttach3=('both', 'both', 'both'))
    cmds.text(parent=row, label='Converted Resolution:')
    convertedResWidthTextField = cmds.textField(parent=row, text='512')
    convertedResHeightTextField = cmds.textField(parent=row, text='512')

    def make_p2t():
        target_mesh = cmds.textField(targetMeshTextField, q=True, text=True)
        config_path = os.path.join(os.path.abspath(cmds.textField(workingDirTextField, q=True,  text=True)), 'config.xml')
        # TODO generate config file from configuration parameters
        if not cmds.objExists(target_mesh):
            cmds.confirmDialog(
                title='Error: Invalid target mesh',
                message='Specified target mesh \'{}\' does not exist'.format(target_mesh),
                button='OK')
            return None
        assert os.path.exists(config_path)
        return Proj2Tex(target_mesh, **parse_config(config_path))

    def makeProjections(*args):
        make_p2t().make_projections()

    def saveScreenshots(*args):
        make_p2t().save_screenshots()

    def makeLayeredShader(*args):
        make_p2t().make_layered_shader()

    def convert(*args):
        make_p2t().convert()

    def combine(*args):
        make_p2t().combine()

    def applyToSingleShader(*args):
        make_p2t().apply_to_single_shader()

    def reset(*args):
        make_p2t().clear_nodes()

    p2tButtons = [
        cmds.button(parent=column, label='1. Make Projections', command=makeProjections),
        cmds.button(parent=column, label='2. Save Screenshots', command=saveScreenshots),
        cmds.button(parent=column, label='3. Make Layered Shader', command=makeLayeredShader),
        cmds.button(parent=column, label='4. Convert Projections To Textures', command=convert),
        cmds.button(parent=column, label='5. Combine Textures', command=combine),
        cmds.button(parent=column, label='6. Apply To Single Shader', command=applyToSingleShader),
        cmds.button(parent=column, label='Reset', command=reset)
    ]
    for btn in p2tButtons:
        cmds.button(btn, edit=True, enable=False)

    cmds.showWindow(window)
    cmds.window(window, edit=True, width=400, height=600, sizeable=False)