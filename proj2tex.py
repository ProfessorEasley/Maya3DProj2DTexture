import maya.cmds as cmds
import maya.utils
import maya.mel
import maya.OpenMayaUI as OpenMayaUI
import maya.OpenMaya as OpenMaya
import os.path
import math
import subprocess
import shutil

from typing import Optional

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
                 combined_image_path: str, screenshot_res=(1280, 720), baked_texture_res=(512, 512)):
        self.target_mesh = target_mesh
        self.projections = projections
        self.layers = layers
        self.combined_image_path = combined_image_path
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

    def make_projections(self):
        xmin, ymin, zmin, xmax, ymax, zmax = cmds.exactWorldBoundingBox(self.target_mesh, calculateExactly=True)
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
        xmin, ymin, zmin, xmax, ymax, zmax = cmds.exactWorldBoundingBox(self.target_mesh, calculateExactly=True)
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

                cmds.select(self.target_mesh)
                cmds.viewFit(scr_cam, fitFactor=0.95)

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
        return '{}_material'.format(self.target_mesh)

    def make_layered_shader(self):
        for proj in self.projections:
            cmds.shadingNode('file', name=proj.file(), asTexture=True, isColorManaged=True)
            cmds.setAttr(proj.file() + '.fileTextureName', proj.image_path, type='string')
            cmds.connectAttr(proj.file() + '.outColor', proj.projection() + '.image')
        cmds.shadingNode('layeredShader', name=self._layered_shader(), asShader=True)
        cmds.setAttr(self._layered_shader() + '.compositingFlag', 1)
        for index in range(len(self.layers)):
            l = self.layers[index]
            cmds.shadingNode('lambert', name=l.layer_material(), asShader=True)
            cmds.setAttr(l.layer_material() + '.diffuse', 1.0)
            cmds.setAttr(l.layer_material() + '.translucence', 0.0)
            cmds.setAttr(l.layer_material() + '.translucenceDepth', 0.0)
            cmds.setAttr(l.layer_material() + '.translucenceFocus', 0.0)
            color_proj = self._find_projection_by_name(l.color_proj_name)
            cmds.connectAttr(color_proj.projection() + '.outColor', l.layer_material() + '.color')
            if l.transparency_proj_name is not None:
                transp_proj = self._find_projection_by_name(l.transparency_proj_name)
                cmds.connectAttr(transp_proj.projection() + '.outColor', l.layer_material() + '.transparency')
            layer_mat = l.layer_material()
            cmds.connectAttr(layer_mat + '.outColor', self._layered_shader() + '.inputs[{}].color'.format(index))
            cmds.connectAttr(layer_mat + '.outTransparency', self._layered_shader() + '.inputs[{}].transparency'.format(index))
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
        pass