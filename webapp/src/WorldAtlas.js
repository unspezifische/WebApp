import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import AddIcon from '@mui/icons-material/Add';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import CloseIcon from '@mui/icons-material/Close';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import PublicIcon from '@mui/icons-material/Public';
import AtlasViewport from './AtlasViewport';
import './SettlementManager.css';

const TYPES = ['hamlet', 'village', 'town', 'city', 'fortress', 'port', 'ruin', 'other'];
const DEFAULT_POPULATIONS = { hamlet: 100, village: 500, town: 2500, city: 8000, fortress: 1200, port: 4000, ruin: 0, other: 500 };
const EMPTY_OPTIONS = { governments: [], biomes: [], resources: [], races: ['Human', 'Elf', 'Dwarf', 'Halfling', 'Gnome'], factions: [], inherited: {} };

function newDraft() {
  return {
    name: '', settlement_type: 'town', population: 2500, atlas_x: null, atlas_y: null,
    environment: { biome: 'temperate grassland', coastal: false, river: false, forest: false, resources: [] },
    primary_race: 'Human', secondary_race: 'Elf', secondary_percentage: 10,
    factions_text: '', government: 'council', seed: '', blank_canvas: false,
  };
}

function GenerationWorkflow({ draft, setDraft, options, step, setStep, onCancel, onSubmit, busy }) {
  const environment = draft.environment;
  const toggleResource = (resource) => setDraft((value) => ({ ...value, environment: { ...value.environment, resources: value.environment.resources.includes(resource) ? value.environment.resources.filter((item) => item !== resource) : [...value.environment.resources, resource] } }));
  return <div className="generation-workflow" role="dialog" aria-modal="true" aria-labelledby="generation-title">
    <header><div><span>SETTLEMENT GENERATOR</span><h2 id="generation-title">{draft.name || 'A new place in the world'}</h2></div><button type="button" onClick={onCancel} aria-label="Close"><CloseIcon/></button></header>
    <nav>{['Place', 'People', 'Govern'].map((label, index) => <button type="button" key={label} className={step === index ? 'active' : step > index ? 'complete' : ''} onClick={() => setStep(index)}><b>{index + 1}</b>{label}</button>)}</nav>
    {step === 0 && <section>
      <p className="workflow-intro">Choose a location on the overworld first. Its environment becomes an input to roads, water, terrain, resources, and the buildings the local economy can support.</p>
      <div className="workflow-grid two"><label>Name<input autoFocus value={draft.name} onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))} placeholder="Settlement name"/></label><label>Scale<select value={draft.settlement_type} onChange={(event) => { const settlement_type = event.target.value; setDraft((value) => ({ ...value, settlement_type, population: DEFAULT_POPULATIONS[settlement_type] })); }}>{TYPES.map((type) => <option key={type}>{type}</option>)}</select></label><label>Population<input type="number" min="0" max="250000" value={draft.population} onChange={(event) => setDraft((value) => ({ ...value, population: Number(event.target.value) }))}/></label><label>Biome<select value={environment.biome} onChange={(event) => setDraft((value) => ({ ...value, environment: { ...value.environment, biome: event.target.value } }))}>{(options.biomes.length ? options.biomes : ['temperate grassland']).map((biome) => <option key={biome}>{biome}</option>)}</select></label></div>
      <div className="location-readout"><PublicIcon/><div><strong>{draft.atlas_x == null ? 'Click the overworld map to locate this settlement' : `Location selected · ${Math.round(draft.atlas_x * 100)}%, ${Math.round(draft.atlas_y * 100)}%`}</strong><small>Coordinates stay relative to the atlas even if its background art changes.</small></div></div>
      <div className="feature-toggles">{[['coastal', 'Coastline'], ['river', 'River'], ['forest', 'Forest']].map(([key, label]) => <label key={key}><input type="checkbox" checked={environment[key]} onChange={(event) => setDraft((value) => ({ ...value, environment: { ...value.environment, [key]: event.target.checked } }))}/>{label}</label>)}</div>
      <div className="resource-picker"><strong>Nearby raw resources</strong><div>{options.resources.map((resource) => <button type="button" key={resource} className={environment.resources.includes(resource) ? 'active' : ''} onClick={() => toggleResource(resource)}>{resource}</button>)}</div></div>
    </section>}
    {step === 1 && <section>
      <p className="workflow-intro">Campaign races and factions are offered first, so this settlement belongs to the same world. Adjust the local mix without changing the world-level definitions.</p>
      <div className="workflow-grid two"><label>Largest population<select value={draft.primary_race} onChange={(event) => setDraft((value) => ({ ...value, primary_race: event.target.value }))}>{options.races.map((race) => <option key={race}>{race}</option>)}</select></label><label>Secondary population<select value={draft.secondary_race} onChange={(event) => setDraft((value) => ({ ...value, secondary_race: event.target.value }))}>{options.races.filter((race) => race !== draft.primary_race).map((race) => <option key={race}>{race}</option>)}</select></label><label>Secondary share <strong>{draft.secondary_percentage}%</strong><input type="range" min="0" max="50" step="1" value={draft.secondary_percentage} onChange={(event) => setDraft((value) => ({ ...value, secondary_percentage: Number(event.target.value) }))}/></label><label>Local & world factions<input list="world-factions" value={draft.factions_text} onChange={(event) => setDraft((value) => ({ ...value, factions_text: event.target.value }))} placeholder="Harper cell, Merchants Guild"/><datalist id="world-factions">{options.factions.map((faction) => <option key={faction} value={faction}/>)}</datalist></label></div>
      {(options.inherited?.races?.length > 0 || options.inherited?.factions?.length > 0) && <div className="inherited-context"><strong>Inherited from this campaign</strong><p>{[...(options.inherited.races || []), ...(options.inherited.factions || [])].filter((value, index, all) => all.indexOf(value) === index).join(' · ')}</p></div>}
    </section>}
    {step === 2 && <section>
      <p className="workflow-intro">Government creates the first civic anchor. Economic dependencies then choose a representative mix of homes and workplaces before roads and districts are drawn around them.</p>
      <div className="government-picker">{options.governments.map((government) => <button type="button" key={government.key} className={draft.government === government.key ? 'active' : ''} onClick={() => setDraft((value) => ({ ...value, government: government.key }))}><strong>{government.name}</strong><small>{government.building}</small></button>)}</div>
      <label className="seed-field">Generation seed <input value={draft.seed} onChange={(event) => setDraft((value) => ({ ...value, seed: event.target.value }))} placeholder="Optional — reuse to reproduce a layout"/></label>
      <label className="blank-canvas"><input type="checkbox" checked={draft.blank_canvas} onChange={(event) => setDraft((value) => ({ ...value, blank_canvas: event.target.checked }))}/><span><strong>Start with a blank canvas instead</strong><small>No generated terrain, roads, water, districts, or buildings.</small></span></label>
      <div className="generation-summary"><AutoAwesomeIcon/><div><strong>{draft.blank_canvas ? 'Blank settlement record' : `${draft.population.toLocaleString()} residents · editable generated map`}</strong><small>{environment.biome}{environment.coastal ? ' · coast' : ''}{environment.river ? ' · river' : ''} · {options.governments.find((item) => item.key === draft.government)?.name || draft.government}</small></div></div>
    </section>}
    <footer><button type="button" className="secondary" onClick={step ? () => setStep((value) => value - 1) : onCancel}>{step ? 'Back' : 'Cancel'}</button><button type="button" className="primary" disabled={busy || (step === 0 && (!draft.name.trim() || draft.atlas_x == null))} onClick={step < 2 ? () => setStep((value) => value + 1) : onSubmit}>{busy ? 'Generating…' : step < 2 ? 'Continue' : draft.blank_canvas ? 'Create blank settlement' : 'Generate settlement'}</button></footer>
  </div>;
}

export default function WorldAtlas({ headers, socket }) {
  const campaignId = headers?.campaignID || headers?.CampaignID;
  const [atlas, setAtlas] = useState({ atlas: { name: 'Campaign World' }, locations: [] });
  const [options, setOptions] = useState(EMPTY_OPTIONS);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(newDraft);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('Loading World Atlas…');
  const [atlasUpload, setAtlasUpload] = useState({ file: null, attribution: '' });
  const [movingId, setMovingId] = useState(null);
  const [showAtlasUpload, setShowAtlasUpload] = useState(false);

  const load = useCallback(async () => {
    if (!campaignId) return;
    try {
      const [atlasResponse, optionsResponse] = await Promise.all([axios.get(`/api/world-atlas/${campaignId}`, { headers }), axios.get(`/api/world-atlas/${campaignId}/generation-options`, { headers })]);
      setAtlas(atlasResponse.data); setOptions({ ...EMPTY_OPTIONS, ...optionsResponse.data });
      setSelectedId((value) => value || atlasResponse.data.locations?.[0]?.id || null); setStatus('');
    } catch (error) { setStatus(error.response?.data?.message || 'Unable to load the World Atlas'); }
  }, [campaignId, headers]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!socket) return undefined; const update = (event) => { const location = event?.settlement; if (!location || location.campaign_id !== Number(campaignId)) return; setAtlas((value) => ({ ...value, locations: event.action === 'deleted' ? value.locations.filter((item) => item.id !== location.id) : [...value.locations.filter((item) => item.id !== location.id), location] })); }; socket.on('world_atlas_updated', update); return () => socket.off('world_atlas_updated', update); }, [socket, campaignId]);

  const patchLocation = async (location, changes) => { try { const response = await axios.patch(`/api/world-atlas/${campaignId}/settlements/${location.id}`, changes, { headers }); setAtlas((value) => ({ ...value, locations: value.locations.map((item) => item.id === location.id ? response.data : item) })); return response.data; } catch (error) { setStatus(error.response?.data?.message || 'Unable to update settlement'); return null; } };
  const uploadAtlasImage = async (event) => { event.preventDefault(); if (!atlasUpload.file) return; const formElement = event.currentTarget; const form = new FormData(); form.append('file', atlasUpload.file); form.append('name', atlas.atlas?.name || 'Faerûn'); form.append('attribution', atlasUpload.attribution); setStatus('Uploading atlas to PostgreSQL…'); try { const response = await axios.post(`/api/world-atlas/${campaignId}/image`, form, { headers }); setAtlas((value) => ({ ...value, atlas: response.data })); setAtlasUpload({ file: null, attribution: '' }); setStatus('Atlas image stored in the campaign database.'); formElement.reset(); } catch (error) { setStatus(error.response?.data?.message || 'Unable to upload atlas image'); } };

  const createSettlement = async () => {
    if (!draft.name.trim()) return;
    setBusy(true);
    const secondary = draft.primary_race === draft.secondary_race ? 0 : draft.secondary_percentage;
    const payload = { ...draft, generate: !draft.blank_canvas, race_distribution: [{ name: draft.primary_race, percentage: 100 - secondary }, ...(secondary ? [{ name: draft.secondary_race, percentage: secondary }] : [])], factions: draft.factions_text.split(',').map((item) => item.trim()).filter(Boolean) };
    try {
      const response = await axios.post(`/api/world-atlas/${campaignId}/settlements`, payload, { headers });
      setAtlas((value) => ({ ...value, locations: [...value.locations, response.data] })); setSelectedId(response.data.id); setWorkflowOpen(false); setDraft(newDraft()); setStep(0);
      setStatus(`${response.data.name} ${draft.blank_canvas ? 'created' : 'generated'} and placed on the overworld.`);
    } catch (error) { setStatus(error.response?.data?.message || 'Unable to generate settlement'); } finally { setBusy(false); }
  };

  const place = async (atlas_x, atlas_y) => {
    if (workflowOpen) { setDraft((value) => ({ ...value, atlas_x, atlas_y })); setStatus('New settlement location selected.'); return; }
    const moving = atlas.locations.find((item) => item.id === movingId);
    if (moving && await patchLocation(moving, { atlas_x, atlas_y })) { setStatus(`${moving.name} moved on the overworld.`); setMovingId(null); }
  };

  const remove = async (location) => { if (!window.confirm(`Permanently delete ${location.name}? Use “Destroy” if the settlement was lost during the story.`)) return; try { const response = await axios.delete(`/api/world-atlas/${campaignId}/settlements/${location.id}?reason=mistake`, { headers }); setAtlas((value) => { const remaining = value.locations.filter((item) => item.id !== location.id); const replacement = response.data.active_settlement; return { ...value, locations: remaining.length || !replacement ? remaining : [replacement] }; }); setSelectedId(response.data.active_settlement?.id || null); setStatus(`${location.name} deleted.`); } catch (error) { setStatus(error.response?.data?.message || 'Unable to delete settlement'); } };

  const openWorkflow = () => { const next = newDraft(); const inheritedRace = options.inherited?.races?.[0] || options.races[0]; if (inheritedRace) next.primary_race = inheritedRace; next.secondary_race = options.races.find((item) => item !== next.primary_race) || next.primary_race; next.factions_text = (options.inherited?.factions || []).join(', '); setDraft(next); setStep(0); setWorkflowOpen(true); setStatus('Click the overworld to choose where this settlement belongs.'); };

  return <div className="world-atlas-page">
    <header className="atlas-page-header"><div><span>CAMPAIGN CARTOGRAPHY</span><h1>World Atlas</h1><p>Generate settlements from their place in the world, or preserve destroyed places as part of its history.</p></div><strong>{atlas.locations.length} settlements</strong></header>
    <div className="world-atlas standalone">
      <section className="atlas-stage"><div className="atlas-heading"><div><span>OVERWORLD</span><h3>{atlas.atlas?.name || 'Campaign World'}</h3></div>{atlas.atlas?.source_url && <a href={atlas.atlas.source_url} target="_blank" rel="noreferrer">Open reference atlas ↗</a>}</div>
        <AtlasViewport atlas={atlas.atlas} locations={atlas.locations} selectedId={movingId || selectedId} onSelect={setSelectedId} onPlace={place} placementEnabled={workflowOpen || movingId != null} draftMarker={workflowOpen ? draft : null}/><small className="atlas-help">{movingId ? `Click the atlas to set ${atlas.locations.find((item) => item.id === movingId)?.name}'s new position.` : 'Wheel to zoom and drag to pan without leaving this page. Settlement coordinates remain stable as you navigate.'}</small>
      </section>
      <aside className="atlas-list"><div><span>SETTLEMENTS</span><strong>{atlas.locations.length}</strong></div>
        {(!atlas.atlas?.image_url || showAtlasUpload) && <form className="atlas-image-upload" onSubmit={async (event) => { await uploadAtlasImage(event); setShowAtlasUpload(false); }}><strong>World atlas image</strong><small>Upload a map you are permitted to use for this private campaign.</small><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setAtlasUpload((value) => ({ ...value, file: event.target.files?.[0] || null }))}/><input value={atlasUpload.attribution} onChange={(event) => setAtlasUpload((value) => ({ ...value, attribution: event.target.value }))} placeholder="Attribution or source note (optional)"/><button type="submit" disabled={!atlasUpload.file}>Store atlas</button></form>}
        {atlas.atlas?.image_url && !showAtlasUpload && <button type="button" className="atlas-replace-image" onClick={() => setShowAtlasUpload(true)}>Replace world atlas image</button>}
        <button type="button" className="generate-settlement-button" onClick={openWorkflow}><AddIcon/><span><strong>New settlement</strong><small>Generate from world context</small></span></button>
        <div className="atlas-location-list">{atlas.locations.map((item) => <article key={item.id} className={`${item.id === (movingId || selectedId) ? 'active' : ''} ${item.status}`}><button className="atlas-open" onClick={() => setSelectedId(item.id)}><strong>{item.name}</strong><small>{item.settlement_type} · {item.population == null ? 'unknown population' : `${item.population.toLocaleString()} people`} · {item.placed ? `${Math.round(item.atlas_x * 100)}%, ${Math.round(item.atlas_y * 100)}%` : 'Not placed'}</small>{item.environment?.biome && <small>{item.environment.biome}{item.generation_config?.generator && item.generation_config.generator !== 'blank-canvas' ? ' · generated' : ''}</small>}</button><div className="atlas-item-actions"><button onClick={() => { setMovingId(item.id); setSelectedId(item.id); setStatus(`Click the atlas to move ${item.name}.`); }}>Move</button>{item.placed && <button onClick={() => patchLocation(item, { atlas_x: null, atlas_y: null })}>Unplace</button>}<button onClick={() => patchLocation(item, { status: item.status === 'destroyed' ? 'active' : 'destroyed' })}>{item.status === 'destroyed' ? 'Restore' : 'Destroy'}</button><button className="atlas-delete" onClick={() => remove(item)} title={`Permanently delete ${item.name}`}><DeleteOutlineIcon/></button></div></article>)}</div>
        <small className="atlas-status" role="status">{status}</small>
      </aside>
    </div>
    {workflowOpen && <GenerationWorkflow draft={draft} setDraft={setDraft} options={options} step={step} setStep={setStep} onCancel={() => setWorkflowOpen(false)} onSubmit={createSettlement} busy={busy}/>} 
  </div>;
}
