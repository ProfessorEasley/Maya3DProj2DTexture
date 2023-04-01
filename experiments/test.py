import os.path
import proj2tex
import importlib
importlib.reload(proj2tex)

workdir = r"C:\Users\sasha-usc\Documents\526\S23\MayaProjectionBaking\proj2tex\experiments"

p2t = proj2tex.Proj2Tex(
    target_mesh="Sentinel_GEO", 
    projections=[
        proj2tex.Projection("frontProj", proj2tex.DIRECTION_FRONT, os.path.join(workdir, "front.png")),
        proj2tex.Projection("sideProj", proj2tex.DIRECTION_SIDE, os.path.join(workdir, "side.png")),
        proj2tex.Projection("backProj", proj2tex.DIRECTION_BACK, os.path.join(workdir, "back.png"))
    ],
    layers=[
        proj2tex.Layer("frontLayer", "frontProj", None),
        proj2tex.Layer("backLayer", "backProj", "sideProj")
    ],
    combined_image_path=os.path.join(workdir, "combined.png"))

p2t.clear_nodes()
p2t.make_projections()
