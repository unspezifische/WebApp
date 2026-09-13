import React, { useEffect, useMemo, useState, useRef } from 'react';
import { Engine, Scene, useScene } from 'react-babylonjs';


import { Scene as BabylonScene } from '@babylonjs/core/scene';

import { VertexBuffer } from '@babylonjs/core/Meshes/buffer';

import { Color3, Color4 } from '@babylonjs/core/Maths/math.color';
import { Vector3 } from '@babylonjs/core/Maths/math.vector';
import { Scalar } from '@babylonjs/core/Maths/math.scalar';
import { Constants } from '@babylonjs/core/Engines/constants';

import { Mesh, MeshBuilder, VertexData } from '@babylonjs/core/Meshes';

import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';

import { DefaultRenderingPipeline } from '@babylonjs/core/PostProcesses/RenderPipeline/Pipelines/defaultRenderingPipeline';

import { PBRMaterial, StandardMaterial, ShaderMaterial, DynamicTexture, RawTexture, Texture, ImageProcessingConfiguration } from '@babylonjs/core/Materials';

import { SceneLoader } from '@babylonjs/core/Loading/sceneLoader';
import { ParticleSystem } from '@babylonjs/core/Particles/particleSystem';
import { Sound } from '@babylonjs/core/Audio/sound';
import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera';


// ==============================================================================
// GLOBAL SHADER STORE & LIGHTING REGISTRY INJECTIONS
// ==============================================================================
import "@babylonjs/core/Materials/standardMaterial"; // Standard shading pipelines
import "@babylonjs/core/Shaders/pbr.fragment";        // GLSL Fragment shaders
import "@babylonjs/core/Shaders/pbr.vertex";          // GLSL Vertex shaders
import "@babylonjs/core/Lights/Shadows/index";        // COMPLETE light and shadow registries


// Utilities
import { LightGizmo } from '@babylonjs/core/Gizmos/lightGizmo';
import "@babylonjs/core/Debug/debugLayer";
import "@babylonjs/inspector";

// Optimized Extension & Loader Sub-Paths
import { Atmosphere } from "@babylonjs/addons/atmosphere";
import HavokPhysics from "@babylonjs/havok";

// Optimized glTF Loader target (Omits legacy v1 parsing frameworks)
import '@babylonjs/loaders/glTF/2.0/glTFLoader';

// Workspace file relative bindings
import {
  FEET_PER_SCENE_UNIT,
  terrainHeightAt,
  createTerrainHeightSampler
} from './settlementEditor';

import {
  fortificationVertexData,
  oceanVertexData,
  regionVertexData,
  riverVertexData,
  roadVertexData,
  terrainVertexData,
  worldToBabylon,
  getReferenceLayerTransform,
} from './settlementBabylon';

import { createSettlementBabylonWorkflow } from './settlementBabylonWorkflow';

const ROAD_COLORS = { cobblestone: '#827d72', brick: '#995d49', paved: '#777876', dirt: '#9b7650', wood: '#866447', stone: '#898982' };
const REGION_COLORS = { city: '#c79b54', forest: '#326a3f', swamp: '#4f6b59', grassland: '#78a35d', farmland: '#b59a52', pasture: '#91ad6c' };

function material(scene, name, hex, alpha = 1, useVertexColors = false) {
  const value = new PBRMaterial(name, scene);
  value.albedoColor = Color3.FromHexString(hex);
  value.metallic = 0.0;
  value.roughness = 0.95;
  value.alpha = alpha;
  value.backFaceCulling = false;
  if (useVertexColors) {
    value.useVertexColor = true; // Tells the PBR shader to expect vertex colors
    value.vertexColor = Color3.White();
  }
  return value;
}

function meshFromData(scene, name, data, meshMaterial, metadata, hasVertexColors = false, updatable = false) {
  const mesh = new Mesh(name, scene);
  data.applyToMesh(mesh, updatable);
  mesh.material = meshMaterial;
  mesh.metadata = metadata;
  if (hasVertexColors) {
    mesh.useVertexColors = true; // Only enable if the VertexData actually contains colors
  }
  return mesh;
}

export function getGerstnerWaveHeightAt(x, z, timeTime) {
  const getWaveOffset = (dir, steepness, wavelength, speed) => {
    const k = 2.0 * 3.14159265 / wavelength; // Changed float to const
    const c = Math.sqrt(9.81 / k) * speed;    // Changed float to const
    const f = k * ((dir.x * x + dir.y * z) - c * timeTime); // Changed float to const
    return (steepness / k) * Math.sin(f);
  };

  // Maps identical wave wavelength configurations to the Step 1 shader code
  const h1 = getWaveOffset({ x: 1.0, y: 0.2 }, 0.18, 12.0, 1.0);
  const h2 = getWaveOffset({ x: -0.4, y: 0.9 }, 0.12, 6.0, 1.3);
  const h3 = getWaveOffset({ x: 0.2, y: -0.8 }, 0.08, 3.5, 0.8);

  return h1 + h2 + h3;
}

function waterMaterial(scene, name, hex, animate, state) {
  const value = new PBRMaterial(name, scene);

  // Glossy water attributes...
  value.albedoColor = Color3.FromHexString(hex);
  value.metallic = 0.02;
  value.roughness = 0.05;

  // value.indexOfRefraction = 1.333; // True water refraction index metric


  // --- BUILD ZERO-DEPENDENCY PROCEDURAL NORMAL MAP ---
  const size = 128;
  const buffer = new Uint8Array(size * size * 4);

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const idx = (y * size + x) * 4;

      // Calculate continuous wave slope vectors procedurally using cosine frequencies
      const nx = Math.cos((x / size) * Math.PI * 8.0) * 127 + 128;
      const ny = Math.sin((y / size) * Math.PI * 8.0) * 127 + 128;

      buffer[idx] = nx; // Red channel   -> X normal vector offset
      buffer[idx + 1] = ny; // Green channel -> Y normal vector offset
      buffer[idx + 2] = 255;// Blue channel  -> Z up normal vector anchor
      buffer[idx + 3] = 255;// Alpha channel -> Full opacity map
    }
  }

  // Convert the array coordinates straight into a hardware GPU normal map texture
  const proceduralBump = RawTexture.CreateRGBATexture(
    buffer, size, size, scene,
    false, false, Constants.TEXTURE_TRILINEAR_SAMPLINGMODE
  );

  proceduralBump.uScale = 16.0;
  proceduralBump.vScale = 16.0;
  value.bumpTexture = proceduralBump;

  // Move texture offsets over time to generate continuous active shimmering currents
  if (animate) {
    const scrollObserver = scene.onBeforeRenderObservable.add(() => {
      if (state?.activeTool === 'terrain') return;
      const delta = scene.getEngine().getDeltaTime() / 1000;

      proceduralBump.uOffset += 0.012 * delta;
      proceduralBump.vOffset += 0.006 * delta;
    });

    value.onDisposeObservable.add(() => {
      scene.onBeforeRenderObservable.remove(scrollObserver);
      proceduralBump.dispose();
    });
  }

  return value; // 100% compatible with Atmosphere scattering out-of-the-box!
}


function createBabylonRegionMesh(scene, region, state) {
  // Calculate the geographic bounding box center of the points
  const points = region.points || [];
  if (!points.length) return [];

  const pointCount = points.length;
  let totalX = 0;
  let totalY = 0;

  for (let i = 0; i < pointCount; i++) {
    totalX += points[i].x;
    totalY += points[i].y;
  }

  const centerX = totalX / Math.max(1, pointCount);
  const centerY = totalY / Math.max(1, pointCount);
  const centerElevation = terrainHeightAt(state.strokes, centerX, centerY, state.heightMap);

  // Build the Crisp Footprint Edge Line
  const outlinePoints = [...points, points[0]].map(point =>
    worldToBabylon(point.x, point.y, terrainHeightAt(state.strokes, point.x, point.y, state.heightMap) + 2.5)
  );

  const outline = MeshBuilder.CreateLines(`region-outline-${region.id}`, { points: outlinePoints }, scene);
  outline.color = Color3.FromHexString(REGION_COLORS[region.region_type] || REGION_COLORS.grassland);
  outline.metadata = { settlement: true, kind: 'region', item: region };

  // Create a clean Floating 3D Text Disc or Billboard Label in the middle
  const labelText = region.name || 'Unnamed District';
  const labelPlane = MeshBuilder.CreatePlane(`region-label-${region.id}`, { width: 120 / FEET_PER_SCENE_UNIT, height: 35 / FEET_PER_SCENE_UNIT }, scene);

  // Elevate it slightly higher to make sure it floats cleanly above nearby trees or cottages
  labelPlane.position = worldToBabylon(centerX, centerY, centerElevation + 64.0); // Increase this value if the label intersects with terrain
  labelPlane.metadata = { settlement: true, kind: 'region', item: region };

  const dynamicTexture = new DynamicTexture(`dynamic-tex-${region.id}`, { width: 512, height: 128 }, scene);
  const textMaterial = new StandardMaterial(`text-mat-${region.id}`, scene);

  // Fix your texture transparency mapping properties
  textMaterial.albedoTexture = dynamicTexture;
  textMaterial.useAlphaFromAlbedoTexture = true; // Force shader to look at transparent pixels
  textMaterial.transparencyMode = StandardMaterial.MATERIAL_ALPHABLEND; // Engage pure blend channels
  textMaterial.backFaceCulling = true; // Hide the inverted backs of text panels completely
  textMaterial.unlit = true; // Keep labels perfectly bright during the night cycle

  labelPlane.billboardMode = Mesh.BILLBOARDMODE_ALL;

  // Clear the background with a completely transparent hex color code context string ('#ffffff00')
  dynamicTexture.drawText(labelText, null, null, "bold 44px sans-serif", "#ffffff", "#ffffff00", true, true);
  labelPlane.material = textMaterial;

  // Return only your outline and text plane, skipping the heavy solid infill poly-meshes completely
  return [outline, labelPlane];
}


function createBabylonWaterMesh(scene, body, state, bounds) {
  if (body.water_type === 'river') return meshFromData(scene, `water-${body.id}`, riverVertexData(body, state.strokes, state.heightMap), waterMaterial(scene, `water-material-${body.id}`, '#338ca0', state.animateWater), { settlement: true, kind: 'water', item: body });
  if (body.water_type === 'ocean') return meshFromData(scene, `water-${body.id}`, oceanVertexData(bounds, state.strokes, state.heightMap, Number(body.surface_elevation_feet) || 0), waterMaterial(scene, `water-material-${body.id}`, '#176b91', state.animateWater), { settlement: true, kind: 'water', item: body });
  if (!body.points?.length || body.points.length < 3) return null;
  const points = body.points.map(point => worldToBabylon(point.x, point.y, Number(body.surface_elevation_feet) || terrainHeightAt(state.strokes, point.x, point.y, state.heightMap) + .7));
  const lake = MeshBuilder.CreatePolygon(`water-${body.id}`, { shape: points }, scene);
  lake.material = waterMaterial(scene, `water-material-${body.id}`, '#338ca0', state.animateWater);
  lake.metadata = { settlement: true, kind: 'water', item: body };
  return lake;
}

function createBabylonExternalAssetModel(scene, buildingMesh, asset, building) {
  if (!asset.model_url) return;
  SceneLoader.ImportMeshAsync('', '', asset.model_url, scene).then(result => result.meshes.forEach(mesh => {
    mesh.parent = buildingMesh;
    mesh.scaling.scaleInPlace(.01);
    mesh.metadata = { settlement: true, kind: 'building', item: building };
  })).catch(() => { });
}

function createBabylonBuiltInBuilding(scene, building, asset, state) {
  const heightFeet = Number(asset.height_feet || 30), elevation = terrainHeightAt(state.strokes, building.x, building.y, state.heightMap) + Number(building.elevation || 0);
  const buildingMesh = MeshBuilder.CreateBox(`building-${building.id}`, { width: Number(building.width_feet) / FEET_PER_SCENE_UNIT, depth: Number(building.depth_feet) / FEET_PER_SCENE_UNIT, height: heightFeet / FEET_PER_SCENE_UNIT }, scene);
  buildingMesh.position = worldToBabylon(building.x, building.y, elevation + heightFeet / 2);
  buildingMesh.rotation.y = -Number(building.rotation || 0);
  buildingMesh.material = material(scene, `building-material-${building.id}`, asset.color || '#a76d43');
  buildingMesh.metadata = { settlement: true, kind: 'building', item: building };
  createBabylonExternalAssetModel(scene, buildingMesh, asset, building);
  return buildingMesh;
}

// Create a reference layer, either projected onto the terrain or as a flat ground plane.
function createBabylonReferenceLayer(scene, layer, state, bounds) {
  // 1. Get the terrain mesh to shrink-wrap
  const terrainMesh = scene.getMeshByName('terrain');
  if (!terrainMesh) {
    console.warn('[Reference] Terrain mesh not found. Cannot create decal.');
    return null;
  }

  // 2. Calculate World-Space Transform
  const transform = getReferenceLayerTransform(layer, state.strokes, state.heightMap);

  // Ensure size is reasonable to prevent degenerate projection boxes
  const size = transform.size.clone();
  if (size.x <= 0 || size.y <= 0) {
    size.x = 10;
    size.y = 10;
  }

  // 3. Create the Decal (Shrink-wraps the terrain geometry)
  const referenceMesh = MeshBuilder.CreateDecal(
    `reference-decal-${layer.id}`,
    terrainMesh,
    {
      position: transform.position,
      normal: transform.normal,
      size: size
    },
    scene
  );

  // Safeguard: If the projection box missed the terrain entirely, log it and abort
  if (!referenceMesh || referenceMesh.getTotalVertices() === 0) {
    console.warn('[Reference] Decal generation failed or empty. The projection box might not intersect the terrain.');
    return null;
  }

  // 4. Apply Rotation
  referenceMesh.rotation.y = transform.rotationY;

  // 5. Setup the Material (Unlit, Emissive, Alpha Blended)
  const referenceMaterial = new StandardMaterial(`ref-mat-${layer.id}`, scene);

  // CRITICAL: Bypass Atmosphere/PBR lighting completely
  referenceMaterial.disableLighting = true;
  referenceMaterial.emissiveColor = Color3.White(); // Full brightness passthrough
  referenceMaterial.diffuseColor = Color3.White();  // Fallback brightness
  referenceMaterial.backFaceCulling = false;

  // 6. Load the Texture & Dynamically Fix Aspect Ratio
  const tex = new Texture(
    layer.image_url,
    scene,
    false, // noMipmap
    false, // invertY
    Texture.TRILINEAR_SAMPLINGMODE,
    () => {
      console.log(`[Success] Loaded decal texture: ${layer.image_url}`);

      // ASPECT RATIO FIX: Once the image loads, calculate its true ratio
      // and adjust the texture scaling so it never stretches, regardless of width_feet/height_feet
      const imgSize = tex.getSize();
      if (imgSize && imgSize.width > 0 && imgSize.height > 0) {
        const imgAspect = imgSize.width / imgSize.height;
        const meshAspect = size.x / size.y;

        if (imgAspect > meshAspect) {
          // Image is wider than the mesh footprint. Fit to width, shrink height.
          tex.vScale = meshAspect / imgAspect;
          tex.vOffset = (1 - tex.vScale) / 2; // Center it vertically
        } else {
          // Image is taller than the mesh footprint. Fit to height, shrink width.
          tex.uScale = imgAspect / meshAspect;
          tex.uOffset = (1 - tex.uScale) / 2; // Center it horizontally
        }
      }
    },
    (msg, exc) => console.error(`[Error] Decal texture failed: ${layer.image_url}`, msg, exc)
  );

  tex.hasAlpha = true;

  // Assign to emissiveTexture so it bypasses lighting/shadows
  referenceMaterial.emissiveTexture = tex;

  // 7. The Opacity Slider (0.0 = hidden, 1.0 = completely blocks terrain)
  referenceMaterial.alpha = Number(layer.opacity ?? 0.7);
  referenceMaterial.transparencyMode = StandardMaterial.MATERIAL_ALPHABLEND;

  referenceMesh.material = referenceMaterial;
  referenceMesh.metadata = { settlement: true, kind: 'reference', item: layer };

  // Ensure it renders in a separate pass just above the terrain to prevent Z-fighting
  referenceMesh.renderingGroupId = 1;

  return referenceMesh;
}


function applyBabylonCameraCommand(camera, command, bounds, strokes, heightMap, settings = {}) {
  if (!command) return;
  const center = worldToBabylon((bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2);
  if (command.mode === 'camera' && command.camera?.position?.length === 3 && command.camera?.target?.length === 3) {
    camera.setPosition(Vector3.FromArray(command.camera.position));
    camera.setTarget(Vector3.FromArray(command.camera.target));
  } else if (command.mode === 'point' && Number.isFinite(Number(command.point?.x)) && Number.isFinite(Number(command.point?.y))) {
    const target = worldToBabylon(Number(command.point.x), Number(command.point.y), Number(command.point.elevation) || 0);
    camera.setTarget(target);
  } else if (command.mode === 'topdown') {
    camera.alpha = -Math.PI / 2;
    camera.beta = .02;
  } else if (command.mode === 'firstPerson') {
    const target = camera.target || center, worldX = target.x * FEET_PER_SCENE_UNIT, worldY = -target.z * FEET_PER_SCENE_UNIT;
    camera.setPosition(new Vector3(target.x, terrainHeightAt(strokes, worldX, worldY, heightMap) / FEET_PER_SCENE_UNIT + (Number(settings.eyeHeight) || 6) / FEET_PER_SCENE_UNIT, target.z));
    camera.radius = .4;
  }
}


function installBabylonCameraControls(scene, camera, getState, onCameraChange) {
  const keys = new Set();
  const editable = target => target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable;
  const key = event => event.code === 'ShiftLeft' ? 'shift' : event.code === 'ControlLeft' ? 'lower' : event.key.toLowerCase();

  const down = event => { if (!editable(event.target)) keys.add(key(event)); };
  const up = event => keys.delete(key(event));

  window.addEventListener('keydown', down);
  window.addEventListener('keyup', up);

  // Clear default Babylon keyboard processing completely so it doesn't fight our manual keys
  if (camera.inputs?.attached?.keyboard) {
    camera.inputs.remove(camera.inputs.attached.keyboard);
  }

  // 🛠️ FIX CAMERA PRESETS: Initialize baseline tracker inside camera metadata
  if (!camera.metadata) camera.metadata = {};
  camera.metadata.lastCommandNonce = null;

  let lastPos = [0, 0, 0];
  let lastTarget = [0, 0, 0];
  const EPSILON = 0.0005;
  const hasSignificantChange = (current, last) => {
    return Math.abs(current[0] - last[0]) > EPSILON ||
      Math.abs(current[1] - last[1]) > EPSILON ||
      Math.abs(current[2] - last[2]) > EPSILON;
  };

  const observer = scene.onBeforeRenderObservable.add(() => {
    const state = getState(), delta = Math.min(scene.getEngine().getDeltaTime() / 1000, .05);
    const active = value => keys.has(value) || state.virtualKeys?.has(value);

    const command = state.viewCommand;
    if (command && command.nonce !== camera.metadata?.lastCommandNonce) {
      applyBabylonCameraCommand(camera, command, state.bounds, state.strokes, state.heightMap, state.firstPersonSettings);
      camera.metadata.lastCommandNonce = command.nonce;
    }

    if (camera.inputs?.attached?.pointers) {
      const pointersInput = camera.inputs.attached.pointers;

      if (state.activeTool === 'terrain') {
        // FIX: Unconditionally remove button 0 (left click) while the terrain tool is active.
        // Checking `data-sculpting` causes a race condition: the camera's internal input captures 
        // the `pointerdown` event and starts dragging BEFORE our observer sets the HTML attribute.
        // By disabling left-click entirely for the camera in this mode, we guarantee the camera 
        // ignores it. Users can still orbit/pan using middle (1) or right (2) mouse buttons.
        pointersInput.buttons = [1, 2];

        // Clear any residual inertia just in case
        camera.inertialAlphaOffset = 0;
        camera.inertialBetaOffset = 0;
        camera.inertialRadiusOffset = 0;
        camera.panningInertia = 0;
      } else {
        pointersInput.buttons = [0, 1, 2]; // Standard tool interaction controls
      }
    }

    // 2. Process Vertical Elevation Changes (Shift / Ctrl)
    let elevationMovement = 0;
    if (active('shift')) elevationMovement += 1;
    if (active('lower')) elevationMovement -= 1;
    if (elevationMovement !== 0 && !state.firstPerson) {
      const speed = Math.max(15, camera.radius * 1.5);
      camera.target.y += elevationMovement * speed * delta;
    }

    // 3. Process Rotations & Alternating Tilts (Q / E / R / F)
    const turn = (active('e') ? 1 : 0) - (active('q') ? 1 : 0);
    const pitch = (active('r') ? 1 : 0) - (active('f') ? 1 : 0);
    camera.alpha += turn * 1.5 * delta;
    camera.beta = Math.max(.02, Math.min(1.55, camera.beta - pitch * 1.2 * delta));

    // 4. Manual Panning Matrix Loop (Independent & Smooth WASD)
    const forward = camera.getForwardRay().direction.clone();
    forward.y = 0;
    forward.normalize();

    const right = new Vector3(forward.z, 0, -forward.x);
    const movement = Vector3.Zero();

    if (active('w') || active('arrowup')) movement.addInPlace(forward);
    if (active('s') || active('arrowdown')) movement.subtractInPlace(forward);
    if (active('d') || active('arrowright')) movement.addInPlace(right);
    if (active('a') || active('arrowleft')) movement.subtractInPlace(right);

    if (movement.lengthSquared() > 0) {
      movement.normalize();
      const baseSpeed = state.firstPerson ? (Number(state.firstPersonSettings?.walkSpeed) || 8) : Math.max(15, camera.radius * 1.8);
      camera.target.addInPlace(movement.scale(baseSpeed * delta));
    }

    if (onCameraChange) {
      const currentPos = camera.position.asArray();
      const currentTarget = camera.target.asArray();
      if (hasSignificantChange(currentPos, lastPos) || hasSignificantChange(currentTarget, lastTarget)) {
        lastPos = currentPos;
        lastTarget = currentTarget;
        onCameraChange({ position: currentPos, target: currentTarget });
      }
    }
  });

  return () => {
    scene.onBeforeRenderObservable.remove(observer);
    window.removeEventListener('keydown', down);
    window.removeEventListener('keyup', up);
  };
}


function installBabylonFirstPersonLook(scene, camera, getState, onPointerLockChange) {
  const canvas = scene.getEngine().getRenderingCanvas();
  const move = event => {
    const state = getState();
    if (!state.firstPerson || document.pointerLockElement !== canvas) return;
    const sensitivity = Math.max(.1, Number(state.firstPersonSettings?.sensitivity) || 50) * .000044;
    camera.alpha += event.movementX * sensitivity * (state.firstPersonSettings?.invertX ? -1 : 1);
    camera.beta = Math.max(.05, Math.min(Math.PI - .05, camera.beta + event.movementY * sensitivity * (state.firstPersonSettings?.invertY ? 1 : -1)));
  };
  const lock = () => onPointerLockChange?.(document.pointerLockElement === canvas);
  document.addEventListener('mousemove', move);
  document.addEventListener('pointerlockchange', lock);
  return () => { document.removeEventListener('mousemove', move); document.removeEventListener('pointerlockchange', lock); if (document.pointerLockElement === canvas) document.exitPointerLock?.(); };
}

function installBabylonScaleObserver(scene, camera, getState, onScaleChange) {
  let previousKey = '';
  let lastRadius = -1;
  const RADIUS_EPSILON = 0.05;

  const observer = scene.onBeforeRenderObservable.add(() => {
    if (!onScaleChange) return;

    if (Math.abs(camera.radius - lastRadius) < RADIUS_EPSILON && previousKey !== '') {
      return;
    }
    lastRadius = camera.radius;

    const state = getState(), canvas = scene.getEngine().getRenderingCanvas();
    if (!canvas?.clientHeight) return;
    const visibleHeightFeet = 2 * Math.tan(camera.fov / 2) * Math.max(.02, camera.radius) * FEET_PER_SCENE_UNIT;
    const feetPerPixel = visibleHeightFeet / canvas.clientHeight;
    const desired = Math.max(.1, feetPerPixel * 110), power = 10 ** Math.floor(Math.log10(desired)), ratio = desired / power;
    const feet = (ratio < 1.5 ? 1 : ratio < 3.5 ? 2 : ratio < 7.5 ? 5 : 10) * power, pixels = feet / feetPerPixel;
    const key = `${feet}:${Math.round(pixels)}`;
    if (key !== previousKey) {
      previousKey = key;
      onScaleChange({ feet, pixels, bounds: state.bounds });
    }
  });
  return () => scene.onBeforeRenderObservable.remove(observer);
}

function SceneContent({ state, meshState, bounds, dusk, onCameraChange, onPointerLockChange, onScaleChange }) {
  const scene = useScene();

  scene.fogMode = BabylonScene.FOGMODE_NONE; // Disable default fog for the scene and let Atmosphere handle it

  // 1. Create refs to hold the latest callback functions and state
  const workflowRef = useRef(null);
  const cameraRef = useRef(null);
  const stateRef = useRef(state);
  stateRef.current = state; // Keep ref synced with latest prop

  const onCameraChangeRef = useRef(onCameraChange);
  const onPointerLockChangeRef = useRef(onPointerLockChange);
  const onScaleChangeRef = useRef(onScaleChange);

  // 2. Update the refs whenever the callbacks change
  useEffect(() => {
    onCameraChangeRef.current = onCameraChange;
    onPointerLockChangeRef.current = onPointerLockChange;
    onScaleChangeRef.current = onScaleChange;
  }, [onCameraChange, onPointerLockChange, onScaleChange]);

  const particleSystemRef = useRef(null);
  const currentSystemKeyRef = useRef('none');
  const lightningFlashRef = useRef({ next: 0, duration: 0 });

  // Persistent Ambient Weather Audio Hook Nodes
  const rainAudioRef = useRef(null);
  const windAudioRef = useRef(null);

  // ==============================================================================
  // 1. MAIN SCENE SETUP (Runs ONLY when `scene` is created)
  // ==============================================================================
  useEffect(() => {
    if (!scene) return undefined;

    // Safely grab the latest bounds from the ref to avoid dependency triggers
    const currentBounds = stateRef.current.bounds || bounds;
    const center = worldToBabylon((currentBounds.minX + currentBounds.maxX) / 2, (currentBounds.minY + currentBounds.maxY) / 2);
    const span = Math.max(currentBounds.width, currentBounds.height) / FEET_PER_SCENE_UNIT;

    const camera = new ArcRotateCamera('settlement-camera', -.75, 1.05, Math.max(12, span * 1.1), center, scene);
    camera.lowerRadiusLimit = .02;
    camera.upperRadiusLimit = Math.max(600, span * 4);
    camera.wheelDeltaPercentage = .015;
    camera.attachControl(scene.getEngine().getRenderingCanvas(), true);
    cameraRef.current = camera;

    const SHOW_INSPECTOR = false;
    if (SHOW_INSPECTOR) {
      scene.debugLayer.show({ embedMode: false, handleResize: true, overlay: true });
    }

    const sunLight = new DirectionalLight('settlement-sun', new Vector3(0, -1, 0), scene);
    const ambientSky = new HemisphericLight('settlement-ambient', new Vector3(0, 1, 0), scene);
    const topDownKey = new DirectionalLight('tabletop-topdown-key', new Vector3(0, -1, 0), scene);

    const atmosphereSupported = Atmosphere.IsSupported(scene.getEngine());
    if (!atmosphereSupported) {
      console.warn('[Settlement] Atmosphere.IsSupported() returned false — falling back to plain lighting.');
    }
    const atmosphere = atmosphereSupported ? new Atmosphere("Atmosphere", scene, [sunLight]) : null;

    const pipeline = new DefaultRenderingPipeline("DefaultPipeline", true, scene);
    if (pipeline.isSupported) {
      pipeline.imageProcessingEnabled = true;
      pipeline.imageProcessing.ditheringEnabled = true;
      pipeline.imageProcessing.toneMappingEnabled = true;
      pipeline.imageProcessing.toneMappingType = ImageProcessingConfiguration.TONEMAPPING_ACES;
    }

    if (atmosphere) {
      atmosphere.minimumMultiScatteringIntensity = 0.1;
      atmosphere.isLinearSpaceLight = true;
    }

    ambientSky.intensity = 0.95;
    ambientSky.groundColor = new Color3(0.25, 0.25, 0.28);
    topDownKey.intensity = 0.65;
    topDownKey.diffuse = new Color3(0.95, 0.95, 1.0);

    const sunGizmo = new LightGizmo();
    sunGizmo.light = sunLight;
    scene.ambientColor = new Color3(0.3, 0.3, 0.35);

    rainAudioRef.current = new Sound("rain-ambient", "/media/sounds/defaults/rain_ambient.mp3", scene, null, { loop: true, autoplay: false, volume: 0 });
    windAudioRef.current = new Sound("wind-ambient", "/media/sounds/defaults/wind_ambient.mp3", scene, null, { loop: true, autoplay: false, volume: 0 });

    const unifiedSceneObserver = scene.onBeforeRenderObservable.add(() => {
      const curState = stateRef.current;
      const timeInfo = curState?.time || { hour: 12, minute: 0 };
      const safeHour = Number.isFinite(timeInfo.hour) ? timeInfo.hour : 12;
      const safeMinute = Number.isFinite(timeInfo.minute) ? timeInfo.minute : 0;
      const config = curState?.weatherSettings || { activeWeather: 'clear', cloudCover: 0, fogDensity: 0.002, fogColor: '#a9c9dc', masterVolume: 0.5 };
      const atmos = curState?.atmosphereSettings || { sunIntensity: 2.2, moonIntensity: 0.15, scatteringScale: 1.0 };
      const delta = scene.getEngine().getDeltaTime() / 1000;
      const volumeScale = config.masterVolume ?? 0.5;

      const absoluteHour = safeHour + (safeMinute / 60);
      const celestialAngle = ((absoluteHour - 6) / 24) * Math.PI * 2;
      const cosAngle = Math.cos(celestialAngle);
      const sinAngle = Math.sin(celestialAngle);

      const sunLightNode = scene.getLightByName('settlement-sun');
      if (sunLightNode) {
        sunLightNode.direction = new Vector3(cosAngle, -sinAngle, 0.2).normalize();
        if (sinAngle > 0) {
          const zenithMultiplier = sinAngle;
          const targetSunIntensity = atmos.sunIntensity ?? 2.2;
          sunLightNode.intensity = zenithMultiplier * targetSunIntensity * (1.0 - config.cloudCover * 0.45);
          sunLightNode.diffuse = Color3.Lerp(new Color3(1.0, 0.78, 0.58), new Color3(1.0, 0.98, 0.95), zenithMultiplier);
        } else {
          sunLightNode.intensity = 0.0;
        }
      }

      if (atmosphere) {
        if (sinAngle <= 0) {
          atmosphere.rayleighScatteringScale = 0.05;
          scene.ambientColor = new Color3(0.02, 0.04, 0.08);
        } else {
          const daylightFactor = sinAngle;
          const targetScatteringScale = atmos.scatteringScale ?? 1.0;
          atmosphere.rayleighScatteringScale = (1.0 - (config.cloudCover * 0.65)) * targetScatteringScale * daylightFactor;
          scene.ambientColor = Color3.Lerp(new Color3(0.08, 0.08, 0.1), new Color3(0.35, 0.35, 0.4), daylightFactor);
        }
      }

      if (particleSystemRef.current && cameraRef.current) {
        particleSystemRef.current.emitter.copyFrom(cameraRef.current.target);
        particleSystemRef.current.emitter.y += 35;
      }

      let targetRainVol = 0, targetWindVol = 0;
      if (config.activeWeather === 'light-drizzle') { targetRainVol = 0.25; targetWindVol = 0.1; }
      else if (config.activeWeather === 'pouring-rain') { targetRainVol = 0.75; targetWindVol = 0.3; }
      else if (config.activeWeather === 'thunderstorm') { targetRainVol = 0.95; targetWindVol = 0.5; }
      else if (config.activeWeather === 'foggy') { targetWindVol = 0.25; }
      else if (config.activeWeather === 'snowing') { targetWindVol = 0.15; }

      const applyAudioChannel = (soundNode, targetVol) => {
        if (!soundNode || !soundNode.isReady) return;
        if (targetVol > 0 && !soundNode.isPlaying) soundNode.play();
        const nextVol = Scalar.Lerp(soundNode.getVolume(), targetVol * volumeScale, 1.5 * delta);
        soundNode.setVolume(Number.isFinite(nextVol) ? nextVol : 0.0);
        if (nextVol <= 0.001 && soundNode.isPlaying) soundNode.stop();
      };

      applyAudioChannel(rainAudioRef.current, targetRainVol);
      applyAudioChannel(windAudioRef.current, targetWindVol);

      if (config.activeWeather === 'thunderstorm') {
        const now = Date.now();
        if (now > lightningFlashRef.current.next) {
          lightningFlashRef.current.duration = now + (120 + Math.random() * 200);
          lightningFlashRef.current.next = now + (6000 + Math.random() * 14000);
        }
        if (now < lightningFlashRef.current.duration) {
          if (sunLightNode) sunLightNode.intensity = 7.0;
          scene.ambientColor = new Color3(0.95, 0.95, 1.0);
        }
      }
    });

    const brushRing = MeshBuilder.CreateTorus("sculpt-brush-ring", { diameter: 2, thickness: 0.05, tessellation: 64 }, scene);
    const brushMat = new StandardMaterial("brush-ring-material", scene);
    brushMat.disableLighting = true;
    brushMat.emissiveColor = new Color3(1, 0, 0); // high contrast red for the cursor
    brushMat.backFaceCulling = false;
    brushRing.material = brushMat;
    brushRing.setEnabled(false);
    brushRing.isPickable = false;
    brushRing.renderingGroupId = 1;

    if (stateRef.current.brushMeshRef) stateRef.current.brushMeshRef.current = brushRing;

    workflowRef.current = createSettlementBabylonWorkflow(
      () => stateRef.current,
      () => stateRef.current.brushRadius
    );

    const workflowInstance = workflowRef.current;
    const unbind = workflowInstance && typeof workflowInstance.attach === 'function'
      ? workflowInstance.attach(scene)
      : () => { };

    const removeCameraControls = installBabylonCameraControls(scene, camera, () => stateRef.current, (...args) => onCameraChangeRef.current?.(...args));
    const removeFirstPersonLook = installBabylonFirstPersonLook(scene, camera, () => stateRef.current, (...args) => onPointerLockChangeRef.current?.(...args));
    const removeScaleObserver = installBabylonScaleObserver(scene, camera, () => stateRef.current, (...args) => onScaleChangeRef.current?.(...args));

    return () => {
      unbind();
      removeCameraControls();
      removeFirstPersonLook();
      removeScaleObserver();
      scene.onBeforeRenderObservable.remove(unifiedSceneObserver);
      pipeline.dispose();
      sunGizmo.dispose();
      if (atmosphere) atmosphere.dispose();
      camera.dispose();
      sunLight.dispose();
      brushRing.dispose();
      brushMat.dispose();
      if (stateRef.current.brushMeshRef) stateRef.current.brushMeshRef.current = null;
      if (scene.debugLayer) scene.debugLayer.hide();
      if (particleSystemRef.current) particleSystemRef.current.dispose();
      if (rainAudioRef.current) rainAudioRef.current.dispose();
      if (windAudioRef.current) windAudioRef.current.dispose();
      scene.meshes.filter(mesh => mesh.metadata?.settlement).forEach(mesh => mesh.dispose());
    };
  }, [scene]);


  // ==============================================================================
  // 2. LIGHTWEIGHT BOUNDS UPDATE (Safely updates camera limits without rebuilding)
  // ==============================================================================
  useEffect(() => {
    if (cameraRef.current && bounds) {
      const span = Math.max(bounds.width, bounds.height) / FEET_PER_SCENE_UNIT;
      cameraRef.current.upperRadiusLimit = Math.max(600, span * 4);
    }
  }, [bounds]);


  // ==============================================================================
  // 3. MESH REBUILDING (Runs when strokes, meshState, or bounds change)
  // ==============================================================================

  // 3a. Terrain Mesh Rebuild (Runs when strokes, meshState, or bounds change)
  useEffect(() => {
    if (!scene) return undefined;
    const currentState = stateRef.current;

    const currentTerrainMaterial = currentState.terrainMaterial || { sea_level_feet: 0, snow_line_feet: 900, snow_blend_feet: 500, cliff_normal_threshold: 0.86, regions: [] };
    const terrainData = terrainVertexData(currentState.strokes, bounds, currentState.heightMap, currentTerrainMaterial);

    let terrain = scene.getMeshByName('terrain');
    if (!terrain) {
      const terrainMat = material(scene, 'terrain-material', '#ffffff', 1, true);
      terrain = meshFromData(scene, 'terrain', terrainData, terrainMat, { settlement: true, kind: 'terrain' }, true, true);
    } else {
      terrain.updateVerticesData(VertexBuffer.PositionKind, terrainData.positions, true);
      terrain.updateVerticesData(VertexBuffer.NormalKind, terrainData.normals, true);
      if (terrainData.colors) terrain.updateVerticesData(VertexBuffer.ColorKind, terrainData.colors, true);
      terrain.refreshBoundingInfo(); // important — picking uses this, and it's stale otherwise
    }

    return () => { /* only dispose on unmount, not on every stroke */ };
  }, [scene, state.strokes, state.heightMap, state.terrainMaterial, bounds]);


  // 3b. Settlement Mesh Rebuild (Runs when roads, fortifications, or other settlement elements change)
  useEffect(() => {
    if (!scene) return undefined;
    const currentState = stateRef.current;
    const transient = [];
    
    console.log('[DEBUG] Settlement Mesh Rebuild Triggered. Total strokes:', currentState.strokes?.length || 0);
    console.log('[DEBUG] Settlement Mesh Rebuild Triggered. Current bounds:', bounds);

    // Dispose old settlement meshes
    scene.meshes.filter(mesh => mesh.metadata?.settlement && mesh.name !== 'terrain').forEach(mesh => mesh.dispose());

    // 1. Build Custom Texturized Landscape Map Base -- NOW OWNED BY the terrain mesh rebuild effect

    // 2. Render Roads Sub-Layers
    (currentState.roads || []).filter(road => road.visible !== false).forEach(road => {
      const data = roadVertexData(road, currentState.strokes, currentState.heightMap, bounds);
      const mat = material(scene, `road-material-${road.id}`, ROAD_COLORS[road.surface_type] || ROAD_COLORS.cobblestone, Number(road.opacity ?? .78));
      transient.push(meshFromData(scene, `road-${road.id}`, data, mat, { settlement: true, kind: 'road', item: road }));
    });

    // 3. Render Fortifications (Walls + Tower Intersections)
    (currentState.fortifications || []).filter(wall => wall.visible !== false).forEach(wall => {
      const data = fortificationVertexData(wall, currentState.strokes, currentState.heightMap);
      const mat = material(scene, `wall-material-${wall.id}`, '#82786a');
      const wallMesh = meshFromData(scene, `wall-${wall.id}`, data, mat, { settlement: true, kind: 'wall', item: wall });
      transient.push(wallMesh);

      const heightSampler = createTerrainHeightSampler(currentState.strokes, currentState.heightMap);
      (wall.points || []).filter((_, idx) => idx === 0 || idx === (wall.points.length - 1) || idx % 2 === 0).forEach((pt, index) => {
        const base = heightSampler(pt.x, pt.y);
        const wallH = Number(wall.height_feet) || 35;
        const radiusFeet = ((Number(wall.width_feet) || 24) * 1.65) / 2;
        const tower = MeshBuilder.CreateCylinder(`tower-${wall.id}-${index}`, { diameter: (radiusFeet * 2) / FEET_PER_SCENE_UNIT, height: wallH / FEET_PER_SCENE_UNIT, tessellation: 12 }, scene);
        tower.position = worldToBabylon(pt.x, pt.y, base + wallH / 2);
        tower.material = material(scene, `tower-mat-${wall.id}-${index}`, '#756c60');
        tower.metadata = { settlement: true, kind: 'wall', item: wall };
        transient.push(tower);
      });
    });

    // 4. Districts Overlay Bounds
    (currentState.regions || []).filter(region => region.visible !== false && region.points?.length >= 3).forEach(region => {
      transient.push(...createBabylonRegionMesh(scene, region, currentState));
    });

    // 5. Water Systems
    const activeTimeTracker = { current: 0 };
    (currentState.waterBodies || []).forEach(body => {
      // FIX 3: Changed `state` to `currentState` for consistency and to avoid stale closures
      const waterMesh = createBabylonWaterMesh(scene, body, currentState, bounds);
      if (!waterMesh) return;
      transient.push(waterMesh);

      if (body.water_type === 'ocean' && currentState.animateWater) {
        const vertexDataRaw = waterMesh.getVerticesData(VertexData.PositionKind);
        if (vertexDataRaw) {
          const originalPositions = Float32Array.from(vertexDataRaw);
          const waveDeformerObserver = scene.onBeforeRenderObservable.add(() => {
            if (stateRef.current?.activeTool === 'terrain') return;
            const deltaSeconds = scene.getEngine().getDeltaTime() / 1000;
            activeTimeTracker.current += deltaSeconds;
            const t = activeTimeTracker.current;
            const positions = waterMesh.getVerticesData(VertexData.PositionKind);
            if (!positions) return;
            const totalVertices = positions.length / 3;
            for (let i = 0; i < totalVertices; i++) {
              const index = i * 3;
              const baseWorldX = originalPositions[index] * FEET_PER_SCENE_UNIT;
              const baseWorldZ = originalPositions[index + 2] * FEET_PER_SCENE_UNIT;
              const waveHeightFeet = getGerstnerWaveHeightAt(baseWorldX, baseWorldZ, t);
              positions[index + 1] = (Number(body.surface_elevation_feet || 0) + waveHeightFeet) / FEET_PER_SCENE_UNIT;
            }
            waterMesh.updateVerticesData(VertexData.PositionKind, positions);
          });
          transient.push({ dispose: () => scene.onBeforeRenderObservable.remove(waveDeformerObserver) });
        }
      }
    });

    // 6. Buildings and Sailing Ships Tickers
    const assets = Object.fromEntries((currentState.assets || []).map(asset => [asset.key, asset]));
    const physicsObserver = scene.onBeforeRenderObservable.add(() => {
      if (currentState.activeTool === 'terrain') return;
      activeTimeTracker.current += scene.getEngine().getDeltaTime() / 1000;
    });
    transient.push({ dispose: () => scene.onBeforeRenderObservable.remove(physicsObserver) });

    (currentState.buildings || []).filter(building => building.visible !== false).forEach(building => {
      const asset = assets[building.asset_key] || {};
      const mesh = createBabylonBuiltInBuilding(scene, building, asset, currentState);
      transient.push(mesh);

      if (['ship', 'boat', 'longship', 'barge', 'galleon'].includes(asset.category || asset.key)) {
        const meshTimeObserver = scene.onBeforeRenderObservable.add(() => {
          if (currentState.activeTool === 'terrain') return;
          const t = activeTimeTracker.current;
          const wH = getGerstnerWaveHeightAt(mesh.position.x, mesh.position.z, t);
          const fO = getGerstnerWaveHeightAt(mesh.position.x, mesh.position.z + 0.5, t);
          const lO = getGerstnerWaveHeightAt(mesh.position.x + 0.5, mesh.position.z, t);
          mesh.position.y = (wH / FEET_PER_SCENE_UNIT) + 0.15;
          mesh.rotation.x = (fO - wH) * 0.8;
          mesh.rotation.z = (lO - wH) * 0.8;
        });
        transient.push({ dispose: () => scene.onBeforeRenderObservable.remove(meshTimeObserver) });
      }
    });

    // 7. Render Points of Interest Markers
    (currentState.pointsOfInterest || []).forEach(point => {
      if (!Number.isFinite(Number(point?.x)) || !Number.isFinite(Number(point?.y))) return;
      const heightSampler = createTerrainHeightSampler(currentState.strokes, currentState.heightMap);
      const surfaceElevation = heightSampler(Number(point.x), Number(point.y));
      const finalElevation = surfaceElevation + (Number(point.elevation) || 0) + 7.0;
      const poiMesh = MeshBuilder.CreateSphere(`poi-${point.id}`, { diameter: 0.5 }, scene);
      poiMesh.position = worldToBabylon(Number(point.x), Number(point.y), finalElevation);
      const poiMaterial = new StandardMaterial(`poi-mat-${point.id}`, scene);
      poiMaterial.albedoColor = new Color3(0.9, 0.77, 0.43);
      poiMaterial.emissiveColor = new Color3(0.5, 0.35, 0.12);
      poiMaterial.specularPower = 64;
      poiMesh.material = poiMaterial;
      poiMesh.metadata = { settlement: true, kind: 'poi', item: point };
      transient.push(poiMesh);
    });

    // 8. Map Canvas Trace References
    (currentState.referenceLayers || []).filter(layer => layer.visible && layer.image_url).forEach(layer => {
      transient.push(createBabylonReferenceLayer(scene, layer, currentState, bounds));
    });

    return () => transient.filter(Boolean).forEach(mesh => mesh.dispose());
  }, [scene, state.buildings, state.roads, state.fortifications, state.regions, state.waterBodies, state.referenceLayers, state.pointsOfInterest, state.assets, bounds]);

  return null;
}


export default function BabylonSettlementHost({ state, meshState, bounds, dusk, brushRadius, onCameraChange, onPointerLockChange, onScaleChange }) {

  return (
    <Engine
      antialias
      adaptToDeviceRatio
      canvasId="settlement-babylon-canvas"
      engineOptions={{ preserveDrawingBuffer: true }}>
      <Scene>
        <SceneContent
          state={state}
          bounds={bounds}
          dusk={dusk}
          meshState={meshState}
          onCameraChange={onCameraChange}
          onPointerLockChange={onPointerLockChange}
          onScaleChange={onScaleChange}
        />
      </Scene>
    </Engine>
  );
}