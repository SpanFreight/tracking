# Container Import Guide

## Required Columns
- **container_number** - The container identification number (e.g., ABCD1234567)
- **container_type** - Type of container (20GP, 40HC, etc.)

## Optional Columns
- **loading_port** - Port of loading
- **final_destination** - Final destination of container
- **opr** - OPR information
- **arrival_date** - Expected arrival date (YYYY-MM-DD)
- **bl_number** - Bill of Lading number
- **status** - Current status (loaded, discharged, emptied, full)
- **date** - Date of status (YYYY-MM-DD)
- **location** - Current container location
- **notes** - Additional notes

## Valid Container Types
- **20GP** - 20 foot General Purpose
- **40GP** - 40 foot General Purpose
- **40HC** - 40 foot High Cube
- **20RF** - 20 foot Refrigerated
- **40RF** - 40 foot Refrigerated
- **20OT** - 20 foot Open Top
- **40OT** - 40 foot Open Top
- **20FR** - 20 foot Flat Rack
- **40FR** - 40 foot Flat Rack

## Valid Status Values
- **loaded** - Container has been loaded
- **discharged** - Container has been discharged from vessel
- **emptied** - Container has been emptied after discharge
- **full** - Container is full
- **in_transit** - Container is in transit
- **customs_hold** - Container is held by customs
- **ready_for_pickup** - Container is ready for pickup
