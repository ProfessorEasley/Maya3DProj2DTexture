import maya.cmds as cmds
import maya.utils
import maya.mel
import maya.OpenMayaUI as OpenMayaUI
import maya.OpenMaya as OpenMaya
import os.path
import math

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

    def material(self):
        return 'projMat_{}'.format(self.name)

class Layer:
    def __init__(self, name: str, color_proj_name: str, transparency_proj_name: Optional[str]):
        self.name = name
        self.color_proj_name = color_proj_name
        self.transparency_proj_name = transparency_proj_name

class Proj2Tex:
    def __init__(self, target_mesh: str, projections: list[Projection], layers: list[Layer], combined_image_path: str):
        self.target_mesh = target_mesh
        self.projections = projections
        self.layers = layers
        self.combined_image_path = combined_image_path

    def clear_nodes(self):
        for proj in self.projections:
            if cmds.objExists(proj.place3dTexture()):
                cmds.delete(proj.place3dTexture())
            if cmds.objExists(proj.projection()):
                cmds.delete(proj.projection())
            if cmds.objExists(proj.material()):
                cmds.delete(proj.material())

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
            cmds.shadingNode('lambert', name=proj.material(), asShader=True)
            cmds.connectAttr(proj.projection() + '.outColor', proj.material() + '.color')

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
        bbox_pts = [
            [xmin, ymin, zmin],
            [xmin, ymin, zmax],
            [xmin, ymax, zmin],
            [xmin, ymax, zmax],
            [xmax, ymin, zmin],
            [xmax, ymin, zmax],
            [xmax, ymax, zmin],
            [xmax, ymax, zmax]
        ]
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
            cmds.window(window, edit=True, width=1280, height=720)
            cmds.modelEditor(meditor, edit=True, camera=scr_cam, displayAppearance='wireframe',
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

                crop_xmin = float('inf')
                crop_ymin = float('inf')
                crop_xmax = -float('inf')
                crop_ymax = -float('inf')
                for pt in bbox_pts:
                    x, y, unclipped = Proj2Tex._world_to_viewport_pt(view, pt)
                    assert unclipped
                    crop_xmin = min(crop_xmin, x)
                    crop_ymin = min(crop_ymin, y)
                    crop_xmax = max(crop_xmax, x)
                    crop_ymax = max(crop_ymax, y)

                tmp_image_path = proj.image_path + '.tmp' + os.path.splitext(proj.image_path)[1]
                cmds.playblast(filename=tmp_image_path, editorPanelName=meditor, st=1, et=1, format='image',
                               width=viewWidth, height=viewHeight, viewer=False)

                print(proj.name, crop_xmin, crop_ymin, crop_xmax, crop_ymax)

                screenshotWidth = view.playblastPortWidth()
                screenshotHeight = view.playblastPortHeight()

                ss_crop_xmin = int(crop_xmin/viewWidth*screenshotWidth)
                ss_crop_ymin = screenshotHeight - int(crop_ymax/viewHeight*screenshotHeight)
                ss_crop_xmax = int(crop_xmax/viewWidth*screenshotWidth)
                ss_crop_ymax = screenshotHeight - int(crop_ymin/viewHeight*screenshotHeight)

                # print('crop {}: {} {} {} {}'.format(proj.name, ss_crop_xmin, ss_crop_ymin, ss_crop_xmax, ss_crop_ymax))

        finally:
            cmds.deleteUI(meditor)
            cmds.deleteUI(window)
            cmds.delete(scr_cam)


    def make_layered_shader(self):
        pass

    def convert(self):
        pass

    def combine(self):
        pass

    def apply_to_single_shader(self):
        pass