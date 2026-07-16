# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project creates blender scripts to create objects in blender. A second purpose is to create gcode files for a CNC machine to execute

## Repo Architecture

Each sign that is getting designed will have it's own directory in the signs directory.

```
signs/   Next.js 16 app (to be built)
  [name of sign]/
    PLAN.md                 Plan for building this sign
    VectorContent.stl       Vector graphics file with the content for this sign                               
    [name of sign].py       script to create the blender object 
    [name of sign].nc       gcode file 
docs/       Planning documents
```

## Sign Design Guide

The standard height of all signs is 10 inches high. Use the stl dimensions to scale the width required.
The standerd border of each sign will have a 3/8" margin around the outside.
At this inside edge of the margin a 1/8" wide border line will go around the whole sign.
Another 3/8" margin will be maintained inside this border line. Content should be expanded to scale so it reaches the inside of this 3/8" margin.
All fonts will be sans serif unless otherwise identified.
Size fonts consistently within each sign element.
If a vector graphic is provided in the sign directory fill the available space with the vector graphic, keeping it's x and y scaling consistent.
All borders, letters and vector graphic shapes are indented 1/4" into the sign's face. 

Write a blender script that creates this sign and name it with the same name as the sign directory with a .py file extension.

## CNC 

The CNC machine that will be used to make the signs is a Sainsmart PROVerXL 6050 with the standard router spindle that comes with it from the factory.