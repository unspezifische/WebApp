import { Color3, Vector3, VertexData } from '@babylonjs/core';
import {
  createTerrainHeightSampler,
  FEET_PER_SCENE_UNIT,
  roadWidthAt,
  terrainSurfaceWeights,
  waterDepthAtSeaLevel,
  terrainHeightAt,
} from './settlementEditor';

export const TERRAIN_SEGMENTS = 256;
const REGION_COLORS = { city: '#c79b54', forest: '#326a3f', swamp: '#4f6b59', grassland: '#78a35d', farmland: '#b59a52', pasture: '#91ad6c' };

export const worldToBabylon = (xFeet, yFeet, elevationFeet = 0) => {
  return new Vector3(
    xFeet / FEET_PER_SCENE_UNIT,
    elevationFeet / FEET_PER_SCENE_UNIT,
    yFeet / FEET_PER_SCENE_UNIT
  );
};

export const babylonToWorld = (point) => {
  return {
    x: point.x * FEET_PER_SCENE_UNIT,
    y: point.z * FEET_PER_SCENE_UNIT,
    elevation: point.y * FEET_PER_SCENE_UNIT,
  };
};

export function pointInsideRegion(x, y, region) {
  let inside = false;
  const points = region?.points || [];
  for (let index = 0, previous = points.length - 1; index < points.length; previous = index++) {
    const current = points[index], prior = points[previous];
    if (((current.y > y) !== (prior.y > y)) && x < (prior.x - current.x) * (y - current.y) / ((prior.y - current.y) || .000001) + current.x) inside = !inside;
  }
  return inside;
}

function colorForTerrain(elevation, x, y, terrainMaterial) {
  const palette = {
    sand: Color3.FromHexString('#cdbb82'), grass: Color3.FromHexString('#66844e'), dirt: Color3.FromHexString('#80684b'), rock: Color3.FromHexString('#77766f'), snow: Color3.FromHexString('#e8edf0'),
  };
  const weights = terrainSurfaceWeights(elevation, 1, terrainMaterial);
  let output = new Color3(0, 0, 0);
  Object.entries(weights).forEach(([surface, weight]) => output.addInPlace(palette[surface].scale(weight)));

  const region = [...(terrainMaterial?.regions || [])].reverse().find(candidate => pointInsideRegion(x, y, candidate));
  if (region?.region_type === 'city') {
    output = Color3.Lerp(output, palette.dirt, .82);
  } else if (region && REGION_COLORS[region.region_type]) {
    output = Color3.Lerp(output, Color3.FromHexString(REGION_COLORS[region.region_type]), 0.36);
  }
  return output;
}

// settlementBabylon.js
export function getReferenceLayerTransform(layer, strokes, heightMap) {
  const originX = Number(layer.origin_x) || 0;
  const originY = Number(layer.origin_y) || 0;
  const widthFeet = Number(layer.width_feet) || 100;
  const heightFeet = Number(layer.height_feet) || 100;
  const rotationDeg = Number(layer.rotation_degrees) || 0;

  // 1. Find the exact terrain elevation at the center of the reference image
  const centerElevation = terrainHeightAt(strokes, originX, originY, heightMap);

  // 2. Convert to Babylon Scene Units (Vector3)
  const position = worldToBabylon(originX, originY, centerElevation + 0.5); // +0.5 ensures it captures the surface

  // 3. Calculate dimensions in Scene Units
  const size = new Vector3(
    widthFeet / FEET_PER_SCENE_UNIT,
    heightFeet / FEET_PER_SCENE_UNIT,
    50 // The "thickness" of the projection. Must be thick enough to capture hills/valleys
  );

  // 4. Calculate Rotation (Babylon Y-axis is inverted compared to standard 2D math)
  const rotationY = -rotationDeg * (Math.PI / 180);

  return { position, normal: Vector3.Up(), size, rotationY };
}



// 1. TERRAIN BUILDER (Now hooks directly into brush sculpt strokes)
export function terrainVertexData(strokes, bounds, heightMap, terrainMaterial = {}) {
  const sampleHeight = createTerrainHeightSampler(strokes, heightMap);
  const positions = [], indices = [], uvs = [], colors = [];

  for (let row = 0; row <= TERRAIN_SEGMENTS; row += 1) {
    const y = bounds.minY + (row / TERRAIN_SEGMENTS) * bounds.height;

    for (let column = 0; column <= TERRAIN_SEGMENTS; column += 1) {
      const x = bounds.minX + (column / TERRAIN_SEGMENTS) * bounds.width;
      const elevation = sampleHeight(x, y);

      positions.push(x / FEET_PER_SCENE_UNIT, elevation / FEET_PER_SCENE_UNIT, y / FEET_PER_SCENE_UNIT);
      uvs.push(column / TERRAIN_SEGMENTS, row / TERRAIN_SEGMENTS);

      const surface = colorForTerrain(elevation, x, y, terrainMaterial);
      colors.push(surface.r, surface.g, surface.b, 1);
    }
  }

  for (let row = 0; row < TERRAIN_SEGMENTS; row += 1) {
    for (let column = 0; column < TERRAIN_SEGMENTS; column += 1) {
      const a = row * (TERRAIN_SEGMENTS + 1) + column, b = a + 1, c = a + TERRAIN_SEGMENTS + 1, d = c + 1;
      indices.push(a, b, c, b, d, c);
    }
  }

  const normals = [];
  VertexData.ComputeNormals(positions, indices, normals);
  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.uvs = uvs;
  data.colors = colors;
  data.normals = normals;
  return data;
}

// Catmull-Rom math translation layer matching Three.js logic
function catmullRomSpline(p0, p1, p2, p3, t) {
  const t2 = t * t, t3 = t2 * t;
  return new Vector3(
    0.5 * ((2 * p1.x) + (-p0.x + p2.x) * t + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3),
    0, 
    0.5 * ((2 * p1.y) + (-p0.y + p2.y) * t + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 + (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3)
  );
}

function getSplinePoint(points, amount) {
  const len = points.length;
  const scaled = amount * (len - 1);
  const index = Math.min(len - 2, Math.floor(scaled));
  const localT = scaled - index;

  const p0 = points[Math.max(0, index - 1)];
  const p1 = points[index];
  const p2 = points[index + 1];
  const p3 = points[Math.min(len - 1, index + 2)];

  return catmullRomSpline(p0, p1, p2, p3, localT);
}

// 2. ROADS & STREETS COMPILER (Glued smoothly onto terrain)
export function roadVertexData(road, strokes, heightMap, bounds, heightSampler = createTerrainHeightSampler(strokes, heightMap)) {
  const source = (road.points || []).map(point => new Vector3(point.x / FEET_PER_SCENE_UNIT, 0, point.y / FEET_PER_SCENE_UNIT));
  if (source.length < 2) return new VertexData();

  const samples = Math.max(32, source.length * 32);
  const positions = [], indices = [], uvs = [];

  for (let index = 0; index <= samples; index += 1) {
    const amount = index / samples;
    const point = getSplinePoint(source, amount);
    const nearby = getSplinePoint(source, Math.min(1, amount + 1 / samples));

    const tangent = nearby.subtract(point).normalize();
    const halfWidth = roadWidthAt(road, amount) / (2 * FEET_PER_SCENE_UNIT);
    const normal = new Vector3(-tangent.z, 0, tangent.x).scale(halfWidth);

    const left = point.add(normal);
    const right = point.subtract(normal);

    // Map central sample points onto the dynamic height data
    const centerWorldX = point.x * FEET_PER_SCENE_UNIT;
    const centerWorldY = point.z * FEET_PER_SCENE_UNIT;
    const groundElevation = (heightSampler(centerWorldX, centerWorldY) + 0.15) / FEET_PER_SCENE_UNIT;

    positions.push(left.x, groundElevation, left.z, right.x, groundElevation, right.z);
    uvs.push(0, amount * 8, 1, amount * 8);

    if (index < samples) {
      const offset = index * 2;
      indices.push(offset, offset + 2, offset + 1, offset + 1, offset + 2, offset + 3);
    }
  }

  const normals = [];
  VertexData.ComputeNormals(positions, indices, normals);
  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.uvs = uvs;
  data.normals = normals;
  return data;
}


export function fortificationVertexData(wall, strokes, heightMap) {
  const source = (wall.points || []).map(point => new Vector3(point.x / FEET_PER_SCENE_UNIT, 0, point.y / FEET_PER_SCENE_UNIT));
  if (source.length < 2) return new VertexData();

  const samples = Math.max(24, source.length * 18);
  const positions = [], indices = [];
  const halfWidth = (Number(wall.width_feet) || 24) / (2 * FEET_PER_SCENE_UNIT);
  const height = (Number(wall.height_feet) || 35) / FEET_PER_SCENE_UNIT;
  const heightSampler = createTerrainHeightSampler(strokes, heightMap);

  for (let index = 0; index <= samples; index += 1) {
    const amount = index / samples;
    const point = getSplinePoint(source, amount);
    const nearby = getSplinePoint(source, Math.min(1, amount + 1 / samples));

    const tangent = nearby.subtract(point).normalize();
    const normal = new Vector3(-tangent.z, 0, tangent.x).scale(halfWidth);

    const left = point.add(normal);
    const right = point.subtract(normal);

    const centerWorldX = point.x * FEET_PER_SCENE_UNIT;
    const centerWorldY = point.z * FEET_PER_SCENE_UNIT;
    const wallBaseElevation = heightSampler(centerWorldX, centerWorldY) / FEET_PER_SCENE_UNIT;

    // Push 4 vertices per step layer smoothly
    positions.push(
      left.x, wallBaseElevation, left.z,           // [offset + 0] Left Base
      right.x, wallBaseElevation, right.z,         // [offset + 1] Right Base
      left.x, wallBaseElevation + height, left.z,  // [offset + 2] Left Top
      right.x, wallBaseElevation + height, right.z // [offset + 3] Right Top
    );

    if (index < samples) {
      const offset = index * 4;
      const next = offset + 4;

      //  CORRECTED 4-POINT QUAD INDEXING (Constructs clean inner, outer, and top wall faces)
      indices.push(
        // Outer Face Panel
        offset, next, offset + 2,
        offset + 2, next, next + 2,

        // Inner Face Panel
        offset + 1, offset + 3, next + 1,
        offset + 3, next + 3, next + 1,

        // Walkway Top Roof Deck Panel
        offset + 2, next + 2, offset + 3,
        offset + 3, next + 2, next + 3
      );
    }
  }

  const normals = [];
  VertexData.ComputeNormals(positions, indices, normals);
  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.normals = normals;
  return data;
}


// 4. BIOME DISTRICT REGIONS COMPILER
export function regionVertexData(region, strokes, heightMap) {
  const points = region.points || [];
  if (points.length < 3) return new VertexData();

  const minX = Math.min(...points.map(p => p.x)), maxX = Math.max(...points.map(p => p.x));
  const minY = Math.min(...points.map(p => p.y)), maxY = Math.max(...points.map(p => p.y));

  const span = Math.max(maxX - minX, maxY - minY, 1);
  const step = Math.max(12, span / 42);
  const positions = [], indices = [];
  const heightSampler = createTerrainHeightSampler(strokes, heightMap);

  for (let y = minY; y < maxY; y += step) {
    for (let x = minX; x < maxX; x += step) {
      const x2 = Math.min(maxX, x + step), y2 = Math.min(maxY, y + step);
      if (!pointInsideRegion((x + x2) / 2, (y + y2) / 2, region)) continue;

      const offset = positions.length / 3;
      [[x, y], [x2, y], [x2, y2], [x, y2]].forEach(([vx, vy]) => {
        positions.push(vx / FEET_PER_SCENE_UNIT, (heightSampler(vx, vy) + 1.8) / FEET_PER_SCENE_UNIT, vy / FEET_PER_SCENE_UNIT);
      });
      indices.push(offset, offset + 1, offset + 2, offset, offset + 2, offset + 3);
    }
  }

  const normals = [];
  VertexData.ComputeNormals(positions, indices, normals);
  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.normals = normals;
  return data;
}

// 5. RIVER GENERATOR
export function riverVertexData(body, strokes, heightMap) {
  const sourcePoints = [...(body.points || [])];
  if (sourcePoints.length < 2) return new VertexData();
  const heightSampler = createTerrainHeightSampler(strokes, heightMap);
  if (heightSampler(sourcePoints[0].x, sourcePoints[0].y) < heightSampler(sourcePoints.at(-1).x, sourcePoints.at(-1).y)) {
    sourcePoints.reverse();
  }
  const source = sourcePoints.map(p => new Vector3(p.x / FEET_PER_SCENE_UNIT, 0, p.y / FEET_PER_SCENE_UNIT));
  const samples = Math.max(36, source.length * 28); const positions = [], indices = [], uvs = []; let previousHeight = Infinity;
  for (let index = 0; index <= samples; index += 1) {
    const amount = index / samples;
    const point = getSplinePoint(source, amount);
    const nearby = getSplinePoint(source, Math.min(1, amount + 1 / samples));
    const tangent = nearby.subtract(point).normalize();
    const normal = new Vector3(-tangent.z, 0, tangent.x).scale((Number(body.width_feet) || 30) / (2 * FEET_PER_SCENE_UNIT)); const left = point.add(normal);
    const right = point.subtract(normal); const streamWorldX = point.x * FEET_PER_SCENE_UNIT;
    const streamWorldY = point.z * FEET_PER_SCENE_UNIT;
    previousHeight = Math.min(previousHeight, heightSampler(streamWorldX, streamWorldY) - 0.2);
    positions.push(left.x, previousHeight / FEET_PER_SCENE_UNIT, left.z, right.x, previousHeight / FEET_PER_SCENE_UNIT, right.z);
    uvs.push(0, amount * 10, 1, amount * 10);
    if (index < samples) {
      const offset = index * 2;
      indices.push(offset, offset + 2, offset + 1, offset + 1, offset + 2, offset + 3);
    }
  }
  
  const normals = [];
  VertexData.ComputeNormals(positions, indices, normals);
  const data = new VertexData(); data.positions = positions;
  data.indices = indices; data.uvs = uvs; data.normals = normals;
  return data;
}

// 🌊 6. OCEAN PLANE GENERATOR (Added to settlementBabylon.js)
export function oceanVertexData(bounds, strokes, heightMap, seaLevel) {
  const segments = 96;
  const positions = [], indices = [], uvs = [];
  const depths = [], exposures = [];

  const heightSampler = createTerrainHeightSampler(strokes, heightMap);
  const edgeSamples = { west: [], east: [], north: [], south: [] };

  // Sample perimeter elevations to calculate wind/wave orientation matching Three.js logic
  for (let index = 0; index <= segments; index += 1) {
    const amount = index / segments;
    const x = bounds.minX + amount * bounds.width;
    const y = bounds.minY + amount * bounds.height;

    edgeSamples.west.push(heightSampler(bounds.minX, y));
    edgeSamples.east.push(heightSampler(bounds.maxX, y));
    edgeSamples.north.push(heightSampler(x, bounds.maxY));
    edgeSamples.south.push(heightSampler(x, bounds.minY));
  }

  const average = values => values.reduce((sum, val) => sum + val, 0) / Math.max(1, values.length);
  const lowestEdge = Object.entries(edgeSamples).sort((a, b) => average(a[1]) - average(b[1]))[0][0];

  // Set wave trajectory pointing inward from the deepest open boundary
  const waveDirection = {
    west: { x: -1, y: 0 },
    east: { x: 1, y: 0 },
    north: { x: 0, y: 1 },
    south: { x: 0, y: -1 }
  }[lowestEdge];

  // Build the geometric grid structure
  for (let row = 0; row <= segments; row += 1) {
    for (let column = 0; column <= segments; column += 1) {
      const x = bounds.minX + (column / segments) * bounds.width;
      const y = bounds.minY + (row / segments) * bounds.height;

      const depth = waterDepthAtSeaLevel(heightSampler(x, y), seaLevel);
      let exposure = 1.0;

      // Cast obstruction vectors backward toward the ocean body to verify island shielding
      if (depth > 0) {
        const stepDistance = Math.max(bounds.width, bounds.height) / 24;
        for (let distance = stepDistance; distance < Math.max(bounds.width, bounds.height); distance += stepDistance) {
          const sampleX = x + waveDirection.x * distance;
          const sampleY = y + waveDirection.y * distance;

          if (sampleX < bounds.minX || sampleX > bounds.maxX || sampleY < bounds.minY || sampleY > bounds.maxY) {
            break;
          }
          // If waves hit high ground, dampen the wave crest profile behind it
          if (heightSampler(sampleX, sampleY) >= seaLevel) {
            exposure = 0.18;
            break;
          }
        }
      }

      // Push arrays out matching Babylon's X/Y/Z coordinate arrangement (Y is up)
      positions.push(x / FEET_PER_SCENE_UNIT, seaLevel / FEET_PER_SCENE_UNIT, y / FEET_PER_SCENE_UNIT);
      uvs.push(column / segments, row / segments);

      depths.push(depth / FEET_PER_SCENE_UNIT);
      exposures.push(exposure);
    }
  }

  // Construct index winding buffers
  for (let row = 0; row < segments; row += 1) {
    for (let column = 0; column < segments; column += 1) {
      const a = row * (segments + 1) + column;
      const b = a + 1;
      const c = a + segments + 1;
      const d = c + 1;
      indices.push(a, b, c, b, d, c);
    }
  }

  const normals = [];
  VertexData.ComputeNormals(positions, indices, normals);

  const data = new VertexData();
  data.positions = positions;
  data.indices = indices;
  data.uvs = uvs;
  data.normals = normals;

  // Cache structural directional parameters so our shader animation loop knows where waves travel
  data.waveDirection = waveDirection;

  return data;
}
