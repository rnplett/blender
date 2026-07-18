# blender

#blenderCAM settings
#ensure the object is 0.01 above the z=0 plane
#set the between and along values to .01

## SVG pocket

`make-svg-pocket.py` imports an SVG, preserves its aspect ratio while fitting it
inside `MAX_WIDTH` by `MAX_HEIGHT`, and cuts it into the selected mesh. Set
`SVG_FILE`, the size, `BOTTOM_LEFT_X`/`BOTTOM_LEFT_Y`, and `POCKET_DEPTH` at the
top of the script, select exactly one mesh, and run it from Blender's Scripting
workspace. Placement coordinates use the selected object's local X/Y axes.
