"""Zoomed KLayout renders of the routed GDS: scripts/eda.sh "klayout -zz -r pnr/zoom_gds.py" (GDS=... to pick a run)."""
import os, pya
gds = os.environ.get("GDS", "/work/pnr/wb_npu/runs/r4/final/gds/wb_npu.gds")
lyp = os.environ["PDK_ROOT"] + "/sky130A/libs.tech/klayout/tech/sky130A.lyp"
for name, box in [("layout_zoom_cells.png", (600, 200, 640, 225)),
                  ("layout_zoom_sram_edge.png", (560, 160, 640, 210))]:
    v = pya.LayoutView()
    v.load_layout(gds, 0)
    v.load_layer_props(lyp)
    v.set_config("background-color", "#000000")
    v.set_config("grid-visible", "false")
    v.max_hier()
    v.zoom_box(pya.DBox(*box))
    v.save_image("/work/build/" + name, 1400, 875)
    print("wrote", name)
