import { PointerEventTypes, Vector3 } from '@babylonjs/core';
import {
  FEET_PER_SCENE_UNIT,
  createBuilding,
  resizeBuildingFromCorner,
  snapBuildingPlacement,
  snapRegionBoundaryPoint,
  snapRoadNetworkPoint,
  snapRoadSplineTranslation,
  terrainHeightAt,
} from './settlementEditor';
import { babylonToWorld, pointInsideRegion } from './settlementBabylon';


function findDistrictKey(point, regions) {
  const region = (regions || []).find(value => value.visible !== false && pointInsideRegion(point.x, point.y, value));
  return region?.district_key || region?.id || null;
}

function updatePoint(setter, id, index, point, round = false) {
  setter(values => values.map(value => value.id === id ? {
    ...value,
    points: value.points.map((current, pointIndex) => pointIndex === index ? {
      ...current,
      x: round ? Math.round(point.x) : point.x,
      y: round ? Math.round(point.y) : point.y,
    } : current),
  } : value));
}

export function createSettlementBabylonWorkflow(getState, getLatestBrushRadius) {
  let interaction = null;
  let previousSculptPoint = null;
  let flattenTarget = null;
  let sculptGestureId = null;

  const beginSplineMove = (type, item, point) => {
    interaction = { type, id: item.id, start: point, points: item.points.map(value => ({ ...value })) };
  };

  const addTerrainPoint = point => {
    const state = getState();
    if (state.activeTool === 'build') {
      if (state.buildMode === 'refine') return;
      const asset = state.assets.find(value => value.key === state.selectedAssetKey);
      if (!asset) return;
      const building = createBuilding(asset, point, state.buildings, state.roads);
      const districtKey = findDistrictKey(point, state.regions);
      const next = districtKey ? { ...building, district_key: districtKey } : building;
      state.setBuildings(values => [...values, next]);
      state.elected(next);
    } else if (state.activeTool === 'road' && state.roadMode === 'draw-new') {
      state.setRoadDraft(values => [...values, snapRoadNetworkPoint({ ...point, width_feet: state.roadWidth }, state.roads)]);
    } else if (state.activeTool === 'fortification' && state.fortificationMode === 'draw-new') {
      state.setFortificationDraft(values => [...values, { x: Math.round(point.x), y: Math.round(point.y) }]);
    } else if (state.activeTool === 'water' && state.seaLevelPicking) {
      state.onSeaLevelPick(point.elevation);
    } else if (state.activeTool === 'water') {
      state.setWaterDraft(values => [...values, { x: Math.round(point.x), y: Math.round(point.y) }]);
    } else if (state.activeTool === 'region' && state.regionMode === 'draw-new') {
      state.setRegionDraft(values => {
        const targets = values.length > 2 ? [...state.regions, { id: 'region-draft-start', points: [values[0]] }] : state.regions;
        return [...values, snapRegionBoundaryPoint(point, targets, state.roads, { fortifications: state.fortifications })];
      });
    } else if (state.activeTool === 'travel') state.onWaypoint(point);
    else if (state.activeTool === 'reference') state.onReferencePoint(point);
    else if (state.activeTool === 'inspect') state.setSelected(null);
  };

  const sculpt = point => {
    const state = getState();

    // FIX 1: Lower the threshold. 18% is too large and ignores slow mouse movements.
    // Use 5% of the radius, with a hard minimum of 2 feet to prevent over-firing.
    const minDistance = Math.max(2, state.brushRadius * 0.05);
    if (previousSculptPoint && Math.hypot(point.x - previousSculptPoint.x, point.y - previousSculptPoint.y) < minDistance) return;

    previousSculptPoint = point;
    const stroke = {
      id: `stroke-${Date.now()}`,
      gesture_id: sculptGestureId,
      x: point.x,
      y: point.y,
      radius: state.brushRadius,
      mode: state.terrainMode,
      ...(state.terrainMode === 'raise' || state.terrainMode === 'lower' ? { strength: state.terrainMode === 'raise' ? state.brushStrength : -state.brushStrength } : {
        target_elevation_feet: flattenTarget ?? point.elevation,
        strength: Math.max(.01, Math.min(1, state.brushStrength / 100)),
      }),
    };

    // Optional debug: Uncomment the line below to verify in the console that sculpting is firing
    console.log('Sculpting:', stroke.mode, 'at', point.x, point.y);

    state.onSculptStroke(stroke);
  };

  const applyDrag = point => {
    if (!interaction) return;
    const state = getState();
    if (interaction.type === 'building') state.setBuildings(values => values.map(building => building.id === interaction.id ? snapBuildingPlacement({ ...building, x: point.x, y: point.y }, state.buildings, state.roads) : building));
    else if (interaction.type === 'building-resize') state.setBuildings(values => values.map(building => building.id === interaction.id ? resizeBuildingFromCorner(building, point, interaction.corner, state.roads) : building));
    else if (interaction.type === 'road-point') updatePoint(state.setRoads, interaction.id, interaction.index, snapRoadNetworkPoint(point, state.roads, { roadId: interaction.id }));
    else if (interaction.type === 'wall-point') updatePoint(state.setFortifications, interaction.id, interaction.index, point, true);
    else if (interaction.type === 'region-point') state.setRegions(values => values.map(region => region.id === interaction.id ? { ...region, points: region.points.map((value, index) => index === interaction.index ? snapRegionBoundaryPoint(point, values, state.roads, { regionId: interaction.id, pointIndex: index, fortifications: state.fortifications }) : value) } : region));
    else if (interaction.type.endsWith('-spline')) {
      const dx = Math.round(point.x - interaction.start.x), dy = Math.round(point.y - interaction.start.y), translated = interaction.points.map(value => ({ ...value, x: value.x + dx, y: value.y + dy }));
      if (interaction.type === 'road-spline') state.setRoads(values => values.map(road => road.id === interaction.id ? { ...road, points: snapRoadSplineTranslation(translated, values, { roadId: interaction.id }) } : road));
      else if (interaction.type === 'wall-spline') state.setFortifications(values => values.map(wall => wall.id === interaction.id ? { ...wall, points: translated } : wall));
      else state.setRegions(values => values.map(region => region.id === interaction.id ? { ...region, points: translated } : region));
    }
  };


  const selectMesh = (metadata, point, event) => {
    const state = getState(), item = metadata?.item;
    if (!item) return false;

    // Rule 1: Clicked on a Built Building Mesh (Your Points of Interest)
    if (metadata.kind === 'building' || metadata.kind === 'poi') {
      state.setSelected(item); // Maps raw object record straight to top-level state slot

      if (['inspect', 'player'].includes(state.activeTool)) {
        state.setInspectSelection({
          kind: item.building_type || item.business_type || 'Point of Interest',
          name: item.name || 'Unnamed Structure',
          description: item.description || `Mapped POI structural footprint located at coordinate boundaries.`
        });
      }

      // If active tool is build-refine, enable dragging/resizing handles
      if (state.activeTool === 'build' && state.buildMode === 'refine' && event.button === 0) {
        interaction = { type: 'building', id: item.id };
      }
      return true;
    }

    // Rule 2: Clicked on a Rendered Spline Road
    else if (metadata.kind === 'road') {
      state.setSelectedRoadId(item.id);
      state.setSelected(item);

      if (['inspect', 'player'].includes(state.activeTool)) {
        state.setInspectSelection({
          kind: 'Street / Highway',
          name: item.name || 'Unnamed Roadway',
          description: `A ${item.road_class || 'standard'} spline track segment running through the district map grids.`
        });
      }

      if (state.activeTool === 'road' && state.roadMode === 'move-spline') {
        beginSplineMove('road-spline', item, point);
      }
      return true;
    }

    // Rule 3: Clicked on a Fortification Wall segment (Walls and Fortifications are identical)
    else if (metadata.kind === 'wall' || metadata.kind === 'fortification') {
      state.setSelectedFortificationId(item.id);
      state.setSelected(item); // Synchronizes structural reference into selection space

      if (['inspect', 'player'].includes(state.activeTool)) {
        state.setInspectSelection({
          kind: 'Wall / Fortification',
          name: item.name || 'Unnamed Perimeter Wall',
          description: item.description || `Defensive masonry barrier standing ${item.height_feet || 35} feet high with structural tower bastions.`
        });
      }

      if (state.activeTool === 'fortification' && state.fortificationMode === 'move-spline') {
        beginSplineMove('wall-spline', item, point);
      }
      return true;
    }

    // Rule 4: Clicked on a District Region (skips raw poly clicks to let details pass through)
    else if (metadata.kind === 'region') {
      if (state.activeTool === 'region' && state.regionMode === 'move-spline') {
        state.setSelectedRegionId(item.id);
        state.setSelected(item);
        beginSplineMove('region-spline', item, point);
        return true;
      }
      return false;
    }

    // Rule 5: Clicked on an Interactive River Water Body
    else if (metadata.kind === 'water') {
      if (item.water_type === 'river' && ['inspect', 'player'].includes(state.activeTool)) {
        state.setSelected(item);
        state.setInspectSelection({
          kind: 'Waterway / River',
          name: item.name || 'Local Stream',
          description: `A discrete flowing landmark river current measured at an average depth of ${item.depth_feet || 5} feet.`
        });
        return true;
      }
      return false;
    }

    return false;
  };


  return {
    attach(scene) {
      const canvas = scene.getEngine().getRenderingCanvas();

      // 1. Add the observer
      const observer = scene.onPointerObservable.add(info => {
        // console.log('[raw event]', info.type, 'pickedPoint:', !!info.pickInfo?.pickedPoint);
        
        const state = getState();
        const pickPredicate = state.activeTool === 'terrain'
          ? mesh => mesh.name === 'terrain'
          : mesh => mesh.isPickable && mesh.isEnabled();

        const pick = scene.pick(scene.pointerX, scene.pointerY, pickPredicate);
        const pickedPoint = pick?.pickedPoint;
        const brushMesh = getState().brushMeshRef?.current;

        // 1. Maintain cursor visibility over scene geometry elements
        if (state.activeTool === 'terrain' && brushMesh) {
          if (pickedPoint) {
            brushMesh.setEnabled(true);
            brushMesh.position.copyFrom(pickedPoint);
            brushMesh.position.y += 0.2;
          } else {
            const ray = scene.createPickingRay(scene.pointerX, scene.pointerY, null, scene.activeCamera);
            const distance = -ray.origin.y / ray.direction.y;
            if (distance > 0) {
              brushMesh.setEnabled(true);
              brushMesh.position.copyFrom(ray.origin.add(ray.direction.scale(distance)));
              const worldPos = babylonToWorld(brushMesh.position);
              const dynamicHeight = terrainHeightAt(state.strokes, worldPos.x, worldPos.y, state.heightMap);
              brushMesh.position.y = (dynamicHeight / FEET_PER_SCENE_UNIT) + 0.2;
            }
          }
          const currentRadius = getLatestBrushRadius ? getLatestBrushRadius() : state.brushRadius;
          const targetScale = currentRadius / FEET_PER_SCENE_UNIT;
          brushMesh.scaling.set(targetScale, 1.0, targetScale);
        } else if (brushMesh && state.activeTool !== 'terrain') {
          brushMesh.setEnabled(false);
        }

        if (!pickedPoint) return;
        const point = babylonToWorld(pickedPoint), event = info.event;

        // 2. Process Sculpting Inputs Smoothly without detaching camera nodes
        if (info.type === PointerEventTypes.POINTERDOWN && event.button === 0) {
          // POINTERDOWN
          if (state.activeTool === 'terrain') {
            if (canvas) canvas.setAttribute('data-sculpting', 'true');
            sculptGestureId = `sculpt-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`; // was: state.sculptGestureId = ...
            flattenTarget = state.terrainMode === 'flatten' ? terrainHeightAt(state.strokes, point.x, point.y, state.heightMap) : null;
            if (state.onSculptStart) state.onSculptStart();
            sculpt(point);
          }
        } 
        else if (info.type === PointerEventTypes.POINTERMOVE) {
          if (state.activeTool === 'terrain') {
            console.log('[move]', 'gestureId:', sculptGestureId, 'pickedPoint:', !!pickedPoint);
          }
          if (state.activeTool === 'terrain' && sculptGestureId) {
            sculpt(point);
          }
          applyDrag(point);
        } 
        else if (info.type === PointerEventTypes.POINTERUP) {
          if (state.activeTool === 'terrain') {
            if (canvas) canvas.removeAttribute('data-sculpting');
            sculptGestureId = null;
            flattenTarget = null;
            previousSculptPoint = null;

            // FIX: Trigger the end of the sculpt gesture to save the undo/redo snapshot
            if (state.onSculptEnd) state.onSculptEnd();

            if (scene.activeCamera) {
              scene.activeCamera.inertia = 0;
              scene.activeCamera.panningInertia = 0;
              scene.activeCamera.inertialAlphaOffset = 0;
              scene.activeCamera.inertialBetaOffset = 0;
            }
          }
          this.endPointer();
        }
        else if (info.type === PointerEventTypes.POINTERWHEEL && state.activeTool === 'terrain') {
          event.preventDefault();
          event.stopPropagation();
          const delta = event.deltaY || -event.wheelDelta;
          const step = 10;
          const currentRadius = getLatestBrushRadius ? getLatestBrushRadius() : state.brushRadius;
          const nextRadius = delta < 0 ? currentRadius + step : currentRadius - step;
          const clampedRadius = Math.max(30, Math.min(1200, nextRadius));
          if (state.onBrushRadiusChange) {
            state.onBrushRadiusChange(clampedRadius);
          }
        }
      });

      // 2. FIX: Return the cleanup function from `attach` itself, NOT from inside the callback above
      return () => {
        scene.onPointerObservable.remove(observer);
        const brushMesh = getState().brushMeshRef?.current;
        if (brushMesh) brushMesh.dispose();
      };
    },
    beginPointDrag(type, id, index, corner) {
      interaction = { type, id, index, corner };
    },
    endPointer() {
      interaction = null;
      previousSculptPoint = null;
      flattenTarget = null;
      sculptGestureId = null;
    },
  }
};

export const worldPointFromBabylon = point => babylonToWorld(new Vector3(point.x, point.y, point.z));