import React, { useEffect, useMemo, useState, useRef } from 'react';
import Tooltip from '@mui/material/Tooltip';

import EditIcon from '@mui/icons-material/Edit';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';

import HomeWorkIcon from '@mui/icons-material/HomeWork';

import RedoIcon from '@mui/icons-material/Redo';
import UndoIcon from '@mui/icons-material/Undo';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong';
import VisibilityIcon from '@mui/icons-material/Visibility';
import PublicIcon from '@mui/icons-material/Public';

import BabylonSettlementHost from './BabylonSettlementHost';
import { bakeStrokeIntoHeightmap, createDefaultHeightmap } from './settlementEditor';
import './SettlementPresentation.css';
import './SettlementToolPanels.css';

const TERRAIN_SIZE_FEET = 1800;
const DEFAULT_FIRST_PERSON_SETTINGS = { sensitivity: 50, invertX: false, invertY: false, fov: 75, walkSpeed: 8, eyeHeight: 6 };
const DEFAULT_BRUSH_STRENGTHS = { raise: 8, lower: 8, flatten: 35, smooth: 35 };

function editorBounds(referenceLayers, heightMap) {
  const layers = [...(referenceLayers || []).filter(layer => layer.image_url), ...(heightMap ? [heightMap] : [])];
  if (!layers.length) return { minX: -900, maxX: 900, minY: -900, maxY: 900, width: TERRAIN_SIZE_FEET, height: TERRAIN_SIZE_FEET };
  const minX = Math.min(-900, ...layers.map(layer => (Number(layer.origin_x) || 0) - Number(layer.width_feet) / 2));
  const maxX = Math.max(900, ...layers.map(layer => (Number(layer.origin_x) || 0) + Number(layer.width_feet) / 2));
  const minY = Math.min(-900, ...layers.map(layer => (Number(layer.origin_y) || 0) - Number(layer.height_feet) / 2));
  const maxY = Math.max(900, ...layers.map(layer => (Number(layer.origin_y) || 0) + Number(layer.height_feet) / 2));
  return { minX, maxX, minY, maxY, width: maxX - minX, height: maxY - minY };
}

function ToolWorkflow({
  state,
  activeTool,
  assets,
  assetKey,
  setAssetKey,

  selected,
  setSelected,
  inspectSelection,
  setInspectSelection,

  roadMode,
  setRoadMode,
  roadDraft,
  setRoadDraft,
  finishRoad,
  roadWidth,
  setRoadWidth,
  wallMode,
  setWallMode,
  wallDraft,
  setWallDraft,
  finishWall,
  regionMode,
  setRegionMode,
  regionDraft,
  setRegionDraft,
  finishRegion,
  waterType,
  setWaterType,
  waterDraft,
  setWaterDraft,
  finishWater,
  terrainMode,
  setTerrainMode,
  brushRadius,
  setBrushRadius,
  brushStrength,
  setBrushStrength,
  viewCommand,
  atmosphereSettings,
  setAtmosphereSettings,
  weatherSettings,
  setWeatherSettings
}) {
  // Add local UI tracking states specifically dedicated to the input fields inside this view lifecycle
  const [localDay, setLocalDay] = useState(viewCommand?.time?.day ?? 24);
  const [localHour, setLocalHour] = useState(viewCommand?.time?.hour ?? 12);
  const [localMin, setLocalMin] = useState(viewCommand?.time?.minute ?? 0);

  const [roadSearch, setRoadSearch] = useState('');

  // Sync inputs dynamically if time advances smoothly via active server simulation clocks
  useEffect(() => {
    if (viewCommand?.time) {
      setLocalDay(viewCommand.time.day ?? 24);
      setLocalHour(viewCommand.time.hour ?? 12);
      setLocalMin(viewCommand.time.minute ?? 0);
    }
  }, [viewCommand]);


  if (activeTool === 'inspect' && inspectSelection) {
    return (
      <aside className="editor-menu inspect-menu-panel">
        <span>INSPECTOR OVERVIEW</span>

        {inspectSelection ? (
          <div className="road-metadata">
            <small className="control-label-eyebrow" style={{ color: '#7ce6ff', letterSpacing: '1px' }}>
              FEATURE SELECTION
            </small>

            <h3 style={{ margin: '4px 0 2px 0', fontSize: '1.2rem', color: '#fff' }}>
              {inspectSelection.name || 'Unnamed Landmark'}
            </h3>

            <span className="settlement-map-loading-status" style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: '#ffe08a' }}>
              Type: {inspectSelection.kind || 'Point of Interest'}
            </span>

            <p style={{ margin: '12px 0', fontSize: '0.9rem', lineHeight: '1.4', color: '#cbd5e1' }}>
              {inspectSelection.public_description || inspectSelection.description || 'No additional architectural records or historical summary notes are unrolled for this quadrant selection.'}
            </p>

            {inspectSelection.points && (
              <small style={{ display: 'block', color: '#94a3b8', fontSize: '0.75rem' }}>
                Structural Nodes: {inspectSelection.points.length} coordinates mapped
              </small>
            )}

            <button
              type="button"
              className="danger-action"
              style={{ marginTop: '16px', width: '100%' }}
              onClick={() => setInspectSelection(null)}
            >
              Clear Selection
            </button>
          </div>
        ) : (
          <div className="chart-empty" style={{ padding: '24px 8px', textAlign: 'center', color: '#94a3b8' }}>
            <VisibilityIcon style={{ fontSize: '2rem', marginBottom: '8px', color: '#47423a' }} />
            <p style={{ margin: 0, fontSize: '0.9rem' }}>Click directly on a mapped building, street line, or point of interest marker to display its contextual database entries.</p>
          </div>
        )}
      </aside>
    );
  }


  if (activeTool === 'build') return <aside className="editor-menu asset-menu">
    <span>BUILDING ASSETS</span>
      {assets.map(asset =>
        <button type="button" key={asset.key} className={assetKey === asset.key ? 'active' : ''} onClick={() => setAssetKey(asset.key)}>
          <HomeWorkIcon/>
          <span>
            <strong>{asset.name}</strong>
            <small>{asset.width_feet} x {asset.depth_feet} ft</small>
          </span>
        </button>)
      }
      <small>Click terrain to place the selected building.</small>
    </aside>;

  if (activeTool === 'road') {
    const selectedRoad = state.roads?.find(r => r.id === state.selectedRoadId);
    const filteredRoads = state.roads?.filter(r => !roadSearch || (r.name || '').toLowerCase().includes(roadSearch.toLowerCase())) || [];
    const selectedPoint = selectedRoad?.points?.[state.selectedRoadPointIndex];

    return (
      <aside className="editor-menu road-menu secondary-editor-menu">
        <span>STREETS &amp; HIGHWAYS</span>

        <div className="road-mode-tabs">
          <button type="button" className={roadMode === 'select' ? 'active' : ''} onClick={() => setRoadMode('select')}>
            <VisibilityIcon fontSize="small" style={{ marginRight: '4px', verticalAlign: 'middle' }} /> Select
          </button>
          <button type="button" className={roadMode === 'refine' ? 'active' : ''} disabled={!selectedRoad} onClick={() => setRoadMode('refine')}>
            <EditIcon fontSize="small" style={{ marginRight: '4px', verticalAlign: 'middle' }} /> Refine
          </button>
          <button type="button" className={roadMode === 'move-spline' ? 'active' : ''} disabled={!selectedRoad} onClick={() => setRoadMode('move-spline')}>
            <OpenInNewIcon fontSize="small" style={{ marginRight: '4px', verticalAlign: 'middle' }} /> Move Spline
          </button>
          <button type="button" className={roadMode === 'draw-new' ? 'active' : ''} onClick={() => { setRoadDraft([]); setRoadMode('draw-new'); }}>
            <AddIcon fontSize="small" style={{ marginRight: '4px', verticalAlign: 'middle' }} /> Draw
          </button>
        </div>

        <label>
          New Width <strong>{roadWidth} ft</strong>
          <input type="range" min="4" max="120" step="2" value={roadWidth} onChange={event => setRoadWidth(Number(event.target.value))} />
        </label>

        <div className="road-actions">
          <button type="button" disabled={!roadDraft.length} onClick={() => setRoadDraft(p => p.slice(0, -1))}>
            Undo Point
          </button>
          <button type="button" disabled={roadDraft.length < 2} onClick={finishRoad}>
            Finish Road
          </button>
        </div>

        <input
          type="search"
          placeholder="Filter existing roads..."
          value={roadSearch}
          onChange={e => setRoadSearch(e.target.value)}
          style={{ margin: '8px 0', width: '100%' }}
        />

        <div className="street-list">
          {filteredRoads.map(r => (
            <div key={r.id} className={r.id === state.selectedRoadId ? 'active' : ''}>
              <button type="button" onClick={() => { state.setSelectedRoadId(r.id); state.setSelectedRoadPointIndex(null); }}>
                <strong>{r.name || 'Unnamed street'}</strong>
                <small>{r.points?.length || 0} pts</small>
              </button>
            </div>
          ))}
        </div>

        {selectedRoad && (
          <div className="road-metadata">
            <label>
              Rename Road
              <input
                value={selectedRoad.name || ''}
                onChange={e => state.setRoads(v => v.map(old => old.id === selectedRoad.id ? { ...old, name: e.target.value } : old))}
              />
            </label>

            <div className="road-point-picker">
              {selectedRoad.points.map((p, idx) => (
                <button
                  type="button"
                  key={idx}
                  className={state.selectedRoadPointIndex === idx ? 'active' : ''}
                  onClick={() => state.setSelectedRoadPointIndex(idx)}
                >
                  {idx + 1}
                </button>
              ))}
            </div>

            {selectedPoint && (
              <div className="reference-dimensions">
                <label>
                  X
                  <input
                    type="number"
                    value={Math.round(selectedPoint.x)}
                    onChange={e => state.setRoads(v => v.map(r => r.id === selectedRoad.id ? {
                      ...r,
                      points: r.points.map((pt, pi) => pi === state.selectedRoadPointIndex ? { ...pt, x: Number(e.target.value) } : pt)
                    } : r))} />
                </label>
                <label>
                  Y
                  <input
                    type="number"
                    value={Math.round(selectedPoint.y)}
                    onChange={e => state.setRoads(v => v.map(r => r.id === selectedRoad.id ? {
                      ...r,
                      points: r.points.map((pt, pi) => pi === state.selectedRoadPointIndex ? { ...pt, y: Number(e.target.value) } : pt)
                    } : r))} />
                </label>
              </div>
            )}

            <button type="button" className="danger-action" onClick={() => { state.setRoads(v => v.filter(old => old.id !== selectedRoad.id)); state.setSelectedRoadId(null); }}>
              <DeleteIcon fontSize="small" style={{ marginRight: '4px', verticalAlign: 'middle' }} /> Delete Road
            </button>
          </div>
        )}
      </aside>
    );
  }

  
  // Replace the terrain condition inside ToolWorkflow with this version:
  if (activeTool === 'terrain') {
    return (
      <aside className="editor-menu terrain-menu">
        <span>TERRAIN SCULPT</span>

        <div className="terrain-history-actions" style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
          <button
            type="button"
            className="history-btn"
            disabled={!state.handleUndo || state.pastRef?.current?.length === 0} // Note: You may need to expose pastRef to state, or just disable based on a simple check
            onClick={state.handleUndo}
            style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
          >
            <UndoIcon fontSize="small" /> Undo
          </button>
          <button
            type="button"
            className="history-btn"
            disabled={!state.handleRedo || state.futureRef?.current?.length === 0}
            onClick={state.handleRedo}
            style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
          >
            Redo <RedoIcon fontSize="small" />
          </button>
        </div>

        {/* Segmented Mode Picker */}
        <div className="segmented terrain-brush-modes">
          {['raise', 'lower', 'flatten', 'smooth'].map(mode => (
            <button
              type="button"
              key={mode}
              className={terrainMode === mode ? 'active' : ''}
              onClick={() => setTerrainMode(mode)}
            >
              {mode.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Brush Radius Grid with Sliders + Manual Inputs */}
        <div className="form-fields-row" style={{ flexDirection: 'column', gap: '12px', marginTop: '16px' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', justifyContent: 'between', alignItems: 'center', width: '100%' }}>
              <span>Brush Radius (ft)</span>
              <input
                type="number"
                min="30"
                max="1200"
                value={brushRadius}
                onChange={event => setBrushRadius(Math.max(30, Math.min(1200, Number(event.target.value) || 30)))}
                style={{ width: '70px', padding: '2px 4px', textAlign: 'right', background: '#10231f', color: '#fff', border: '1px solid #47423a', borderRadius: '4px' }}
              />
            </div>
            <input
              type="range"
              min="30"
              max="1200"
              step="10"
              value={brushRadius}
              onChange={event => setBrushRadius(Number(event.target.value))}
            />
          </label>

          {/* Brush Strength Grid with Sliders + Manual Inputs */}
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', justifyContent: 'between', alignItems: 'center', width: '100%' }}>
              <span>Brush Strength {['flatten', 'smooth'].includes(terrainMode) ? '(%)' : '(ft)'}</span>
              <input
                type="number"
                min="1"
                max="100"
                value={brushStrength}
                onChange={event => setBrushStrength(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}
                style={{ width: '70px', padding: '2px 4px', textAlign: 'right', background: '#10231f', color: '#fff', border: '1px solid #47423a', borderRadius: '4px' }}
              />
            </div>
            <input
              type="range"
              min="1"
              max="100"
              value={brushStrength}
              onChange={event => setBrushStrength(Number(event.target.value))}
            />
          </label>
        </div>

        <small style={{ marginTop: '12px', display: 'block', color: '#94a3b8', fontSize: '0.8rem', lineHeight: '1.4' }}>
          {terrainMode === 'flatten' ? 'The first point clicked anchors the elevation target for the rest of that continuous drag stroke.' :
            terrainMode === 'smooth' ? 'Blends and averages terrain height vectors dynamically beneath the active brush footprint.' :
              'Left-click and drag across the landscape grid to deform vertices. The brush circle scales automatically.'}
        </small>
      </aside>
    );
  }

  
  const drawing = activeTool === 'road' ? { title: 'SPLINE ROAD', mode: roadMode, setMode: setRoadMode, draft: roadDraft, setDraft: setRoadDraft, finish: finishRoad, minimum: 2 } : activeTool === 'fortification' ? { title: 'FORTIFICATION SPLINE', mode: wallMode, setMode: setWallMode, draft: wallDraft, setDraft: setWallDraft, finish: finishWall, minimum: 2 } : activeTool === 'region' ? { title: 'REGIONS & BIOMES', mode: regionMode, setMode: setRegionMode, draft: regionDraft, setDraft: setRegionDraft, finish: finishRegion, minimum: 3 } : null;
  
  if (drawing) return <aside className="editor-menu road-menu">
    <span>{drawing.title}</span>
    <div className="road-mode-tabs">
      <button type="button" className={drawing.mode === 'select' ? 'active' : ''} onClick={() => drawing.setMode('select')}>Select</button>
      <button type="button" className={drawing.mode === 'draw-new' ? 'active' : ''} onClick={() => { drawing.setDraft([]); drawing.setMode('draw-new'); }}>Draw</button>
  </div>
  
  {activeTool === 'road' && <label>Width <strong>{roadWidth} ft</strong>
  <input type="range" min="4" max="400" step="2" value={roadWidth} onChange={event => setRoadWidth(Number(event.target.value))}/></label>}
  <div className="road-actions">
    <button type="button" disabled={!drawing.draft.length} onClick={() => drawing.setDraft(points => points.slice(0, -1))}>Undo point</button>
    <button type="button" disabled={drawing.draft.length < drawing.minimum} onClick={drawing.finish}>Finish</button>
  </div>
  </aside>;

  if (activeTool === 'water') return <aside className="editor-menu water-menu">
    <span>WATER BODY</span>
    <label>Type<select value={waterType} onChange={event => { setWaterType(event.target.value); setWaterDraft([]); }}>
      <option value="river">River</option>
      <option value="lake">Lake</option>
      <option value="ocean">Ocean</option>
      </select>
    </label>
    <div className="road-actions">
      <button type="button" disabled={!waterDraft.length} onClick={() => setWaterDraft(points => points.slice(0, -1))}>Undo point</button>
      <button type="button" disabled={waterType !== 'ocean' && waterDraft.length < (waterType === 'river' ? 2 : 3)} onClick={finishWater}>Finish water</button>
    </div>
    </aside>;
  if (activeTool === 'timeOfDay') {
    const handleShift = (minutes) => {
      window.dispatchEvent(new CustomEvent('settlement-time-advance-request', {
        detail: { minutes }
      }));
    };

    const handleAbsoluteSubmit = (e) => {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent('settlement-time-absolute-request', {
        detail: {
          day: Math.max(1, Number(localDay) || 1),
          hour: Math.max(0, Math.min(23, Number(localHour) || 0)),
          minute: Math.max(0, Math.min(59, Number(localMin) || 0))
        }
      }));
    };

    return (
      <aside className="editor-menu time-of-day-menu">
        <span>TIME OF DAY TRACKING</span>

        <div className="time-adjustment-grid">
          <button type="button" onClick={() => handleShift(-1440)}>◀ Day</button>
          <button type="button" onClick={() => handleShift(-720)}>◀ 12h</button>
          <button type="button" onClick={() => handleShift(-60)}>◀ Hour</button>

          <button type="button" onClick={() => handleShift(60)}>Hour ▶</button>
          <button type="button" onClick={() => handleShift(720)}>12h ▶</button>
          <button type="button" onClick={() => handleShift(1440)}>Day ▶</button>
        </div>

        <form className="manual-time-override-form" onSubmit={handleAbsoluteSubmit}>
          <div className="override-inputs-row">
            <label>Day<input type="number" min="1" value={localDay} onChange={e => setLocalDay(e.target.value)} /></label>
            <label>Hour<input type="number" min="0" max="23" value={localHour} onChange={e => setLocalHour(e.target.value)} /></label>
            <label>Min<input type="number" min="0" max="59" value={localMin} onChange={e => setLocalMin(e.target.value)} /></label>
          </div>
          <button type="submit" className="apply-time-button">Apply Manual Override</button>
        </form>
      </aside>
    );
  }


  if (activeTool === 'atmosphere' && atmosphereSettings) {
    return (
      <aside className="editor-menu secondary-tool-panel atmosphere-menu">
        <span>ATMOSPHERE PLUGINS</span>
        <label>
          Sun Light Glare
          <input type="range" min="0.5" max="5.0" step="0.1" value={atmosphereSettings.sunIntensity} onChange={e => setAtmosphereSettings(prev => ({ ...prev, sunIntensity: Number(e.target.value) }))} />
        </label>
        <label>
          Moon Base Glow
          <input type="range" min="0.0" max="1.0" step="0.05" value={atmosphereSettings.moonIntensity} onChange={e => setAtmosphereSettings(prev => ({ ...prev, moonIntensity: Number(e.target.value) }))} />
        </label>
        <label>
          Rayleigh Scattering
          <input type="range" min="0.2" max="3.0" step="0.1" value={atmosphereSettings.scatteringScale} onChange={e => setAtmosphereSettings(prev => ({ ...prev, scatteringScale: Number(e.target.value) }))} />
        </label>
      </aside>
    );
  }

  if (activeTool === 'weather' && weatherSettings) {
    const handlePresetChange = (e) => {
      const preset = e.target.value;
      let fallbackFog = 0.002;
      let fallbackColor = "#a9c9dc";
      let fallbackClouds = 0.0;

      if (preset === 'light-drizzle') { fallbackClouds = 0.4; fallbackFog = 0.008; }
      else if (preset === 'pouring-rain') { fallbackClouds = 0.8; fallbackFog = 0.012; }
      else if (preset === 'foggy') { fallbackClouds = 0.5; fallbackFog = 0.045; fallbackColor = "#cbd5e1"; }
      else if (preset === 'snowing') { fallbackClouds = 0.7; fallbackFog = 0.015; fallbackColor = "#e2e8f0"; }
      else if (preset === 'thunderstorm') { fallbackClouds = 1.0; fallbackFog = 0.025; fallbackColor = "#1e293b"; }

      setWeatherSettings(prev => ({
        ...prev,
        activeWeather: preset,
        cloudCover: fallbackClouds,
        fogDensity: fallbackFog,
        fogColor: fallbackColor
      }));
    };

    return (
      <aside className="editor-menu secondary-tool-panel weather-menu">
        <span>WEATHER SYSTEM MATRIX</span>
        <label>
          Condition Selection
          <select value={weatherSettings.activeWeather} onChange={handlePresetChange}>
            <option value="clear">☀️ Clear Skies</option>
            <option value="light-drizzle">🌦️ Light Drizzle</option>
            <option value="pouring-rain">🌧️ Pouring Rain</option>
            <option value="foggy">🌫️ Thick Fog</option>
            <option value="snowing">❄️ Snowing</option>
            <option value="thunderstorm">⛈️ Thunderstorm</option>
          </select>
        </label>

        <label>
          Cloud Density <strong>{Math.round((weatherSettings.cloudCover ?? 0) * 100)}%</strong>
          <input type="range" min="0.0" max="1.0" step="0.05" value={weatherSettings.cloudCover ?? 0} onChange={e => setWeatherSettings(prev => ({ ...prev, cloudCover: Number(e.target.value) }))} />
        </label>

        <label>
          Fog Density Target
          <input type="range" min="0.001" max="0.06" step="0.001" value={weatherSettings.fogDensity} onChange={e => setWeatherSettings(prev => ({ ...prev, fogDensity: Number(e.target.value) }))} />
        </label>

        <label className="audio-mixer-volume-row">
          Environment Volume <strong>{Math.round((weatherSettings.masterVolume ?? 0.5) * 100)}%</strong>
          <input type="range" min="0.0" max="1.0" step="0.05" value={weatherSettings.masterVolume ?? 0.5} onChange={e => setWeatherSettings(prev => ({ ...prev, masterVolume: Number(e.target.value) }))} />
        </label>

        <label>
          Fog Tint Color
          <input type="color" value={weatherSettings.fogColor} onChange={e => setWeatherSettings(prev => ({ ...prev, fogColor: e.target.value }))} />
        </label>
      </aside>
    );
  }

  return null;
}

// ******************************************************************************
// Functions to control map elements- navigation, camera, ToD, Weather, etc.
// ******************************************************************************

function NavigationControlPanel({ viewCommand, setMapEnvironment }) {
  const [isMinimized, setIsMinimized] = useState(false);
  // const stateRef = useRef(new Set());
  
  // Custom pipeline to set state values on the global engine window context
  const setVirtualKey = (keyName, isPressed) => {
    window.dispatchEvent(new CustomEvent('settlement-virtual-key-update', {
      detail: { key: keyName, pressed: isPressed }
    }));
  };

  const handleCommand = (modeType) => {
    // Dispatch instant structural updates back to state frameworks
    // Top-down pushes orbit variables; firstPerson engages gravity on-foot locking
    window.dispatchEvent(new CustomEvent('settlement-camera-command-trigger', {
      detail: { mode: modeType }
    }));
  };

  return (
    <div className={`nav-control-panel-wrapper ${isMinimized ? 'minimized' : ''}`}>
      <button 
        type="button" 
        className="nav-panel-toggle-tab"
        onClick={() => setIsMinimized(!isMinimized)}
        aria-label={isMinimized ? "Expand navigation panel" : "Minimize navigation panel"}
      >
        {isMinimized ? <ArrowBackIcon fontSize="small" /> : <ArrowForwardIcon fontSize="small" />}
      </button>

      {!isMinimized && (
        <div className="nav-panel-content">
          {/* Mode Perspective Changers using MUI Icons */}
          <div className="nav-group view-modes">
          <Tooltip title="Top Down View" arrow placement="top">
            <button type="button" className="button icon-only" onClick={() => handleCommand('topdown')} aria-label="Top Down View">
              <CenterFocusStrongIcon style={{ verticalAlign: 'middle' }} />
            </button>
          </Tooltip>

          <Tooltip title="1st Person Mode" arrow placement="top">
            <button type="button" className="button icon-only" onClick={() => handleCommand('firstPerson')} aria-label="1st Person Mode">
              <VisibilityIcon style={{ verticalAlign: 'middle' }} />
            </button>
          </Tooltip>

          <Tooltip title="Orbit Camera" arrow placement="top">
            <button type="button" className="button icon-only" onClick={() => handleCommand('camera')} aria-label="Orbit Camera">
              <PublicIcon style={{ verticalAlign: 'middle' }} />
            </button>
          </Tooltip>
        </div>

          {/* D-Pad Translation Matrix (WASD equivalent buttons) */}
          <div className="nav-group dpad-grid">
            <button type="button" className="button grid-up" onMouseDown={() => setVirtualKey('w', true)} onMouseUp={() => setVirtualKey('w', false)} onMouseLeave={() => setVirtualKey('w', false)}>▲</button>
            <button type="button" className="button grid-left" onMouseDown={() => setVirtualKey('a', true)} onMouseUp={() => setVirtualKey('a', false)} onMouseLeave={() => setVirtualKey('a', false)}>◀</button>
            <button type="button" className="button grid-down" onMouseDown={() => setVirtualKey('s', true)} onMouseUp={() => setVirtualKey('s', false)} onMouseLeave={() => setVirtualKey('s', false)}>▼</button>
            <button type="button" className="button grid-right" onMouseDown={() => setVirtualKey('d', true)} onMouseUp={() => setVirtualKey('d', false)} onMouseLeave={() => setVirtualKey('d', false)}>▶</button>
          </div>

          {/* Rotations and Alternating Heights (Q/E Orbit, R/F Tilt, Shift/Ctrl Elevate) */}
          <div className="nav-group axis-utilities">
            <div className="utility-row">
              <button type="button" className="button icon-only" onMouseDown={() => setVirtualKey('q', true)} onMouseUp={() => setVirtualKey('q', false)}><UndoIcon style={{ verticalAlign: 'middle' }} />(Q)</button>
              <button type="button" className="button icon-only" onMouseDown={() => setVirtualKey('e', true)} onMouseUp={() => setVirtualKey('e', false)}><RedoIcon style={{ verticalAlign: 'middle' }} />(E)</button>
            </div>
            <div className="utility-row">
              <button type="button" className="button icon-only" onMouseDown={() => setVirtualKey('r', true)} onMouseUp={() => setVirtualKey('r', false)}>Tilt Up (R)</button>
              <button type="button" className="button icon-only" onMouseDown={() => setVirtualKey('f', true)} onMouseUp={() => setVirtualKey('f', false)}>Tilt Dn (F)</button>
            </div>
            <div className="utility-row">
              <button type="button" className="button icon-only" onMouseDown={() => setVirtualKey('shift', true)} onMouseUp={() => setVirtualKey('shift', false)}>Raise (Shift)</button>
              <button type="button" className="button icon-only" onMouseDown={() => setVirtualKey('lower', true)} onMouseUp={() => setVirtualKey('lower', false)}>Lower (Ctrl)</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export const prepareTerrainSavePayload = (state) => {
  const payload = { ...state };

  // 1. Clear out the legacy strokes array to prevent DB bloat
  payload.terrain_strokes = [];

  // 2. Serialize the heightMap into a reference layer
  if (state.heightMap) {
    const heightmapLayer = {
      id: state.heightMap.id || `heightmap-${Date.now()}`,
      layer_type: 'heightmap',
      name: state.heightMap.name || 'Sculpted Terrain',
      grid_width: state.heightMap.grid_width,
      grid_height: state.heightMap.grid_height,
      values: Array.from(state.heightMap.values), // Convert Float32Array to standard Array for JSON
      width_feet: state.heightMap.width_feet,
      height_feet: state.heightMap.height_feet,
      origin_x: state.heightMap.origin_x,
      origin_y: state.heightMap.origin_y,
      min_elevation_feet: state.heightMap.min_elevation_feet,
      max_elevation_feet: state.heightMap.max_elevation_feet,
    };

    // Replace any existing heightmap layer or add a new one
    const existingLayers = (payload.reference_layers || []).filter(l => l.layer_type !== 'heightmap');
    payload.reference_layers = [...existingLayers, heightmapLayer];
  }

  return payload;
};


// This function is the main component for editing the settlement map, handling various tools and interactions.
export default function SettlementMapEditor({
    simulation,
    activeTool,
    atmosphereSettings = { sunIntensity: 2.2, moonIntensity: 0.15, scatteringScale: 1.0 },
    setAtmosphereSettings,
    weatherSettings = { activeWeather: 'clear', fogDensity: 0.01, fogColor: '#a9c9dc' },
    setWeatherSettings,
    assets = [],
    buildings = [],
    setBuildings = () => { },

    selected,
    setSelected,
    inspectSelection,
    setInspectSelection = () => { },
    buildingViewMode = 'satellite',
    roads = [],
    setRoads = () => {},
    strokes = [],
    setStrokes = () => {},
    heightMap = null,
    setHeightMap = () => {},
    waterBodies = [],
    setWaterBodies = () => {},
    mapEnvironment = {},
    setMapEnvironment = () => {},
    setFortifications = () => {},
    dusk,
    lamps = [],
    partyPosition,
    destination,
    onWaypoint = () => {},
    referenceLayers = [],
    onReferencePoint = () => {},
    calibrationPoints = [],
    fitRequest = 0,
    onMapContext = () => {},
    onCameraChange = null,
    viewCommand = null,
    labelState = { ids: [], showAll: false },
    pointsOfInterest = [],
    campaignName = ''
  }) {

  const [assetKey, setAssetKey] = useState(assets[0]?.key || '');

  const [terrainMode, setTerrainMode] = useState('raise')
  const [brushRadius, setBrushRadius] = useState(110)
  const [brushStrengths, setBrushStrengths] = useState(DEFAULT_BRUSH_STRENGTHS);

  const [roadMode, setRoadMode] = useState('select')
  const [roadDraft, setRoadDraft] = useState([])
  const [roadWidth, setRoadWidth] = useState(36);
  const [wallMode, setWallMode] = useState('select')
  const [wallDraft, setWallDraft] = useState([]);
  const [regionMode, setRegionMode] = useState('select')
  const [regionDraft, setRegionDraft] = useState([]);
  const [waterType, setWaterType] = useState('river')
  const [waterDraft, setWaterDraft] = useState([]);

  const [selectedRoadId, setSelectedRoadId] = useState(null);
  const [selectedFortificationId, setSelectedFortificationId] = useState(null);
  const [selectedRegionId, setSelectedRegionId] = useState(null);

  const [virtualKeys, setVirtualKeys] = useState(new Set());
  const [localViewCommand, setLocalViewCommand] = useState(null);
  const [pointerLocked, setPointerLocked] = useState(false);
  const [scaleIndicator, setScaleIndicator] = useState({ feet: 100, pixels: 100 });

  const [firstPersonSettings] = useState(DEFAULT_FIRST_PERSON_SETTINGS);
  // const touchInputRef = useRef({ lookX: 0, lookY: 0, moveX: 0, moveY: 0, sprint: false });

  const bounds = useMemo(
    () => editorBounds(referenceLayers, heightMap),
    [referenceLayers, heightMap?.origin_x, heightMap?.origin_y, heightMap?.width_feet, heightMap?.height_feet]
  );

  const brushMeshRef = useRef(null);

  const regions = useMemo(() => mapEnvironment.regions || [], [mapEnvironment.regions]);
  const fortifications = mapEnvironment.fortifications || [];

  const terrainMaterial = useMemo(() => ({
    sea_level_feet: Number(mapEnvironment.sea_level_feet) || 0,
    snow_line_feet: Number(mapEnvironment.terrain_material?.snow_line_feet ?? 900),
    snow_blend_feet: Number(mapEnvironment.terrain_material?.snow_blend_feet ?? 500),
    cliff_normal_threshold: Number(mapEnvironment.terrain_material?.cliff_normal_threshold ?? .86),
    regions
  }), [mapEnvironment, regions]);

  // ********************************************** //
  // Functions for terrain sculpting with Undo/Redo //
  // ********************************************** //

  const pastRef = useRef([]);
  const futureRef = useRef([]);
  const gestureStartSnapshotRef = useRef(null);

  const onSculptStroke = stroke => {
    const next = {
      ...stroke,
      mode: terrainMode,
      delta: terrainMode === 'raise' ? brushStrength : terrainMode === 'lower' ? -brushStrength : 0,
      amount: terrainMode === 'flatten' || terrainMode === 'smooth' ? brushStrength / 100 : undefined
    };

    // Append the stroke to the array for real-time rendering.
    setStrokes(prev => [...prev, next]);
  };

  const onSculptStart = () => {
    if (heightMap) {
      // Clone the Float32Array before the user starts dragging
      gestureStartSnapshotRef.current = new Float32Array(heightMap.values);
    }
  };

  const onSculptEnd = () => {
    // If no strokes were made during this drag, just reset and exit
    if (strokes.length === 0) {
      gestureStartSnapshotRef.current = null;
      return;
    }

    // 1. Clone current heightMap or create default
    const newHeightMap = heightMap
      ? { ...heightMap, values: new Float32Array(heightMap.values) }
      : createDefaultHeightmap();

    // 2. Bake all accumulated real-time strokes into the cloned heightMap permanently
    strokes.forEach(stroke => {
      bakeStrokeIntoHeightmap(newHeightMap, stroke);
    });

    // 3. Handle undo/redo history using the snapshot we took in onSculptStart
    if (gestureStartSnapshotRef.current) {
      const changed = gestureStartSnapshotRef.current.some((val, idx) => val !== newHeightMap.values[idx]);
      if (changed) {
        pastRef.current.push(gestureStartSnapshotRef.current);
        if (pastRef.current.length > 30) pastRef.current.shift(); // Limit to 30 steps
        futureRef.current = []; // Clear redo stack on new edit
      }
    }

    // 4. Commit the new baked heightMap and clear the temporary strokes
    setHeightMap(newHeightMap);
    setStrokes([]);

    // 5. Reset snapshot for the next gesture
    gestureStartSnapshotRef.current = null;
  };

  const handleUndo = () => {
    if (pastRef.current.length > 0 && heightMap) {
      futureRef.current.push(new Float32Array(heightMap.values));
      const prevState = pastRef.current.pop();
      setHeightMap({ ...heightMap, values: prevState });
    }
  };

  const handleRedo = () => {
    if (futureRef.current.length > 0 && heightMap) {
      pastRef.current.push(new Float32Array(heightMap.values));
      const nextState = futureRef.current.pop();
      setHeightMap({ ...heightMap, values: nextState });
    }
  };

  // ********************************************************* //
  // Hook listeners to intercept virtual panels actions safely //
  // ********************************************************* //
  useEffect(() => {
    const handleKeyUpdate = (e) => {
      const orbitBreakingKeys = new Set(['q', 'e', 'r', 'f', 'shift', 'lower']);

      if (e.detail.pressed && orbitBreakingKeys.has(e.detail.key.toLowerCase())) {
        // If the player is locked on-foot but hits an orbiting utility button,
        // force a camera breakout action to Orbit Cam mode
        setLocalViewCommand(prev => {
          if (prev?.mode === 'firstPerson') {
            return { mode: 'camera', nonce: Date.now() };
          }
          return prev;
        });
      }

      setVirtualKeys(prev => {
        const next = new Set(prev);
        if (e.detail.pressed) next.add(e.detail.key);
        else next.delete(e.detail.key);
        return next;
      });
    };

    const handleCommandUpdate = (e) => {
      // If the command is a structural perspective shift away from 'firstPerson',
      // make sure we notify the parent tree immediately
      setLocalViewCommand({ mode: e.detail.mode, nonce: Date.now() });
    };

    window.addEventListener('settlement-virtual-key-update', handleKeyUpdate);
    window.addEventListener('settlement-camera-command-trigger', handleCommandUpdate);
    return () => {
      window.removeEventListener('settlement-virtual-key-update', handleKeyUpdate);
      window.removeEventListener('settlement-camera-command-trigger', handleCommandUpdate);
    };
  }, []);

  useEffect(() => {
    if (activeTool !== 'terrain') return;

    // Grab handle references to your interactive control panel panels
    const toolPanel = document.querySelector('.terrain-menu'); // Maps to your panel class selector
    const brushMesh = brushMeshRef.current;

    const hideBrush = () => { if (brushMesh) brushMesh.setEnabled(false); };

    if (toolPanel) {
      // If the cursor rolls inside the panel boundary box, force-kill the WebGL preview mesh
      toolPanel.addEventListener('mouseenter', hideBrush);
    }

    return () => {
      if (toolPanel) {
        toolPanel.removeEventListener('mouseenter', hideBrush);
      }
    };
  }, [activeTool]);


  const setRegions = updater => setMapEnvironment(value => ({ ...value, regions: typeof updater === 'function' ? updater(value.regions || []) : updater }));
  const activeViewCommand = localViewCommand || viewCommand, firstPerson = activeViewCommand?.mode === 'firstPerson', brushStrength = brushStrengths[terrainMode];
  
  const finishRoad = () => {
    if (roadDraft.length < 2) return;
    setRoads(values => [...values, { id: `road-${Date.now()}`, name: `New road ${values.length + 1}`, road_class: 'street', surface_type: 'cobblestone', width_feet: roadWidth, opacity: .78, visible: true, points: roadDraft }]);
    setRoadDraft([]);
    setRoadMode('select');
  };

  const finishWall = () => {
    if (wallDraft.length < 2) return;
    setFortifications(values => [...values, { id: `wall-${Date.now()}`, name: `New wall ${values.length + 1}`, wall_type: 'city_wall', width_feet: 24, height_feet: 35, visible: true, points: wallDraft }]);
    setWallDraft([]);
    setWallMode('select');
  };

  const finishRegion = () => {
    if (regionDraft.length < 3) return;
    setRegions(values => [...values, { id: `region-${Date.now()}`, name: `New region ${values.length + 1}`, region_type: 'grassland', visible: true, points: regionDraft }]);
    setRegionDraft([]);
    setRegionMode('select');
  };

  const finishWater = () => {
    if (waterType !== 'ocean' && waterDraft.length < (waterType === 'river' ? 2 : 3)) return;
    setWaterBodies(values => [...values.filter(body => waterType !== 'ocean' || body.water_type !== 'ocean'), { id: `water-${Date.now()}`, name: `New ${waterType}`, water_type: waterType, width_feet: 30, depth_feet: 5, surface_elevation_feet: terrainMaterial.sea_level_feet, points: waterDraft }]);
    setWaterDraft([]);
  };
  
  useEffect(() => {
    if (viewCommand) setLocalViewCommand(viewCommand);
  }, [viewCommand]);
  
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('settlement-first-person-change', { detail: firstPerson }));
  }, [firstPerson]);

  useEffect(() => {
    setSelected?.(null);
    setSelectedRoadId(null);
    setSelectedFortificationId(null);
    setSelectedRegionId(null);
  }, [activeTool, setSelected]);

  const state = {
    activeTool,
    time: simulation?.time || viewCommand?.time || { hour: 12, minute: 0 },

    terrainMaterial: {
      sea_level_feet: Number(mapEnvironment.sea_level_feet) || 0,
      snow_line_feet: Number(mapEnvironment.terrain_material?.snow_line_feet ?? 900),
      snow_blend_feet: Number(mapEnvironment.terrain_material?.snow_blend_feet ?? 500),
      cliff_normal_threshold: Number(mapEnvironment.terrain_material?.cliff_normal_threshold ?? 0.86),
      regions: mapEnvironment.regions || []
    },
    atmosphereSettings,
    weatherSettings,

    assets,
    buildings,
    setBuildings,
    
    selected,
    setSelected,
    inspectSelection,
    setInspectSelection,
    buildingViewMode,
    roads,
    setRoads,
    strokes,
    heightMap,
    setHeightMap,
    waterBodies,
    setWaterBodies,
    bounds,
    regions,
    setRegions,
    fortifications,
    setFortifications,
    roadMode,
    selectedRoadId,
    setSelectedRoadId,
    fortificationMode: wallMode,
    selectedFortificationId,
    setSelectedFortificationId,
    regionMode,
    selectedRegionId,
    setSelectedRegionId,
    selectedAssetKey: assetKey,
    buildMode: 'place',
    roadWidth,
    roadDraft,
    setRoadDraft,
    fortificationDraft: wallDraft,
    setFortificationDraft: setWallDraft,
    regionDraft,
    setRegionDraft,
    waterDraft,
    setWaterDraft,
    seaLevelPicking: false,
    onWaypoint,
    onReferencePoint,
    onMapContext,
    onInspectSelection: setInspectSelection,
    onSeaLevelPick: () => {},

    // Terrain editing related props
    terrainMode,
    brushRadius,
    brushMeshRef,
    onBrushRadiusChange: setBrushRadius,
    brushStrength,
    onSculptStroke,
    onSculptEnd,
    onSculptStart,
    handleUndo,
    handleRedo,

    viewCommand: activeViewCommand,

    firstPersonSettings,
    animateWater: ['inspect', 'player'].includes(activeTool),
    referenceLayers,
    calibrationPoints,
    lamps,
    partyPosition,
    destination,
    pointsOfInterest,
    fitRequest,
    campaignName,
    virtualKeys,
    firstPerson: (localViewCommand || viewCommand)?.mode === 'firstPerson'
  };

  const meshState = useMemo(() => ({
    buildings: state.buildings,
    roads: state.roads,
    fortifications: state.fortifications,
    regions: state.regions,
    waterBodies: state.waterBodies,
    referenceLayers: state.referenceLayers,
    strokes: state.strokes,
    heightMap: state.heightMap,
    terrainMaterial: state.terrainMaterial,
    assets: state.assets,
    pointsOfInterest: state.pointsOfInterest,
    animateWater: state.animateWater,
  }), [
    state.buildings, state.roads, state.fortifications, state.regions,
    state.waterBodies, state.referenceLayers, state.strokes, state.heightMap,
    state.terrainMaterial, state.assets, state.pointsOfInterest, state.animateWater
  ]);
  
  return (
    <>
      <BabylonSettlementHost
        state={state}
        meshState={meshState}
        bounds={bounds}
        dusk={dusk}
        brushRadius={brushRadius}
        brushStrength={brushStrengths[terrainMode]}
        onCameraChange={onCameraChange}
        onPointerLockChange={setPointerLocked}
        onScaleChange={setScaleIndicator}
      />
      <div className="map-scale-indicator" aria-label={`Map scale ${scaleIndicator.feet} feet`}>
        <span style={{ width: `${Math.max(35, Math.min(180, scaleIndicator.pixels))}px` }} />
        <strong>
          {scaleIndicator.feet >= 5280 ? `${(scaleIndicator.feet / 5280).toFixed(1)} mi` : `${scaleIndicator.feet} ft`}
        </strong>
      </div>
      {['inspect', 'player'].includes(activeTool) && inspectSelection && <aside className="inspect-map-selection">
        <button type="button" className="inspect-selection-close" onClick={() => setInspectSelection(null)} aria-label="Close">x</button>
        <span>{inspectSelection.kind}</span>
        <h3>{inspectSelection.name || 'Mapped feature'}</h3>
        <p>{inspectSelection.public_description || inspectSelection.description || inspectSelection.summary || 'Known settlement feature.'}</p>
      </aside>}

      <ToolWorkflow
        state={state}
        activeTool={activeTool}
        viewCommand={activeViewCommand}

        // Brush Configurations
        terrainMode={terrainMode}
        setTerrainMode={setTerrainMode}
        brushRadius={brushRadius}
        setBrushRadius={setBrushRadius} // Passes down your top-level hook setter directly
        brushStrength={brushStrength}
        // Maps value updates straight into your nested strengths array object slot cleanly
        setBrushStrength={value => setBrushStrengths(values => ({ ...values, [terrainMode]: value }))}

        selected={selected}
        setSelected={setSelected}
        inspectSelection={inspectSelection}
        setInspectSelection={setInspectSelection}

        atmosphereSettings={atmosphereSettings}
        setAtmosphereSettings={setAtmosphereSettings}
        weatherSettings={weatherSettings}
        setWeatherSettings={setWeatherSettings}

        assets={assets}
        assetKey={assetKey}
        setAssetKey={setAssetKey}
        roadMode={roadMode}
        setRoadMode={setRoadMode}
        roadDraft={roadDraft}
        setRoadDraft={setRoadDraft}
        finishRoad={finishRoad}
        roadWidth={roadWidth}
        setRoadWidth={setRoadWidth}
        wallMode={wallMode}
        setWallMode={setWallMode}
        wallDraft={wallDraft}
        setWallDraft={setWallDraft}
        finishWall={finishWall}
        regionMode={regionMode}
        setRegionMode={setRegionMode}
        regionDraft={regionDraft}
        setRegionDraft={setRegionDraft}
        finishRegion={finishRegion}
        waterType={waterType}
        setWaterType={setWaterType}
        waterDraft={waterDraft}
        setWaterDraft={setWaterDraft}
        finishWater={finishWater}
      />
      <NavigationControlPanel viewCommand={state.viewCommand} />
    </>
  );
}
