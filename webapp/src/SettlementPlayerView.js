import React, { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { FALLBACK_ASSET_CATALOG } from './settlementEditor';
import './SettlementPlayerView.css';

const SettlementMapEditor = lazy(() => import('./SettlementMapEditor'));

export default function SettlementPlayerView({ headers, socket }) {
  const campaignId = headers?.campaignID || headers?.CampaignID;
  const [map, setMap] = useState({
    buildings: [],
    roads: [],
    terrain_strokes: [],
    water_bodies: [],
    environment: {},
    reference_layers: [],
    asset_catalog: FALLBACK_ASSET_CATALOG,
  });
  const [simulation, setSimulation] = useState({ time: { hour: 12 }, routes: [] });
  const [partyPosition, setPartyPosition] = useState(null);
  const [settlementId, setSettlementId] = useState(null);
  const [settlementName, setSettlementName] = useState('New Settlement');
  const [selectedBuilding,setSelectedBuilding]=useState(null);
  const [status, setStatus] = useState('Loading settlement…');
  const initialParams = new URLSearchParams(window.location.search);
  const requestedSettlementId = Number(initialParams.get('settlementID')) || null;
  const [viewCommand,setViewCommand] = useState(null);
  const [labelState,setLabelState] = useState({ids:(initialParams.get('labels')||'').split(',').filter(Boolean),showAll:initialParams.get('showAllLabels')==='1'});
  const ignoreEdit = useCallback(() => {}, []);

  useEffect(() => {
    if (!campaignId) return undefined;
    let active = true;

    axios.get(`/api/world-atlas/${campaignId}`, { headers }).then((atlasResponse) => {
      const location=atlasResponse.data.locations?.find(item=>item.id===requestedSettlementId)||atlasResponse.data.locations?.find(item=>item.is_primary)||atlasResponse.data.locations?.[0];
      if(!location)throw new Error('No settlement is available.');
      return Promise.all([
      axios.get(`/api/settlement-map/${campaignId}?settlement_id=${location.id}`, { headers }),
      axios.get(`/api/settlement-simulation/${campaignId}`, { headers }),
      axios.get(`/api/travel/${campaignId}/context`, { headers }),
      ]);
    }).then(([mapResponse, simulationResponse, travelResponse]) => {
      if (!active) return;
      setMap(mapResponse.data);
      setSettlementId(mapResponse.data.settlement_id);
      setSettlementName(mapResponse.data.name||'New Settlement');
      setSimulation(simulationResponse.data);
      setPartyPosition(travelResponse.data.party_position || null);
      setStatus('');
    }).catch((error) => {
      console.error('Unable to load the player settlement map:', error);
      if (active) setStatus('Unable to load the settlement map.');
    });

    return () => { active = false; };
  }, [campaignId, headers, requestedSettlementId]);

  useEffect(() => {
    if (!socket) return undefined;
    const updateMap = (nextMap) => {
      if ((!nextMap?.campaign_id || Number(nextMap.campaign_id) === Number(campaignId)) && (!nextMap?.settlement_id || Number(nextMap.settlement_id)===Number(settlementId))) {setMap(nextMap);setSettlementName(nextMap.name||'New Settlement');}
    };
    const updateSimulation = (nextSimulation) => {
      if (!nextSimulation?.campaign_id || Number(nextSimulation.campaign_id) === Number(campaignId)) setSimulation(nextSimulation);
    };
    const updateParty = (position) => setPartyPosition(position);
    const updatePresentation = (command) => {
      if(Number(command?.campaign_id)!==Number(campaignId)||Number(command?.settlement_id)!==Number(settlementId))return;
      if(command.action==='camera')setViewCommand({mode:'camera',camera:command.camera,nonce:Date.now()});
      if(command.action==='focus')setViewCommand({mode:'point',point:command.point,nonce:Date.now()});
      if(command.action==='label')setLabelState(value=>({...value,ids:command.visible?[...new Set([...value.ids,String(command.building_id)])]:value.ids.filter(id=>id!==String(command.building_id))}));
      if(command.action==='labels_all')setLabelState(value=>({...value,showAll:Boolean(command.visible)}));
    };

    socket.on('settlement_map_updated', updateMap);
    socket.on('settlement_simulation_updated', updateSimulation);
    socket.on('party_position_updated', updateParty);
    socket.on('settlement_player_command', updatePresentation);
    return () => {
      socket.off('settlement_map_updated', updateMap);
      socket.off('settlement_simulation_updated', updateSimulation);
      socket.off('party_position_updated', updateParty);
      socket.off('settlement_player_command', updatePresentation);
    };
  }, [socket, campaignId, settlementId]);

  const route = simulation.routes?.[0];
  const hour = simulation.time?.hour ?? 12;
  const minute = simulation.time?.minute ?? 0;

  return (
    <div className="settlement-player-view">
      <Suspense fallback={<div className="settlement-player-loading" role="status"><i/><span>Preparing 3D map…</span></div>}><SettlementMapEditor
        activeTool="player"
        assets={map.asset_catalog?.length ? map.asset_catalog : FALLBACK_ASSET_CATALOG}
        buildings={map.buildings || []}
        setBuildings={ignoreEdit}
        selected={selectedBuilding}
        setSelected={setSelectedBuilding}
        roads={map.roads || []}
        setRoads={ignoreEdit}
        strokes={map.terrain_strokes || []}
        setStrokes={ignoreEdit}
        heightMap={(map.reference_layers || []).find(layer=>layer.layer_type==='heightmap') || null}
        setHeightMap={ignoreEdit}
        waterBodies={map.water_bodies || []}
        setWaterBodies={ignoreEdit}
        mapEnvironment={map.environment || {}}
        dusk={hour >= 18 || hour < 6}
        lamps={route?.lamps || []}
        partyPosition={partyPosition}
        destination={null}
        onWaypoint={ignoreEdit}
        referenceLayers={(map.reference_layers || []).filter(layer=>layer.layer_type!=='heightmap')}
        fitRequest={(map.reference_layers || []).length ? 1 : 0}
        viewCommand={viewCommand}
        labelState={labelState}
        campaignName={headers?.campaignName || headers?.CampaignName || initialParams.get('campaignName') || ''}
      /></Suspense>
      <div className="settlement-player-status" aria-live="polite">
        <strong>{settlementName}</strong>
        <span>{status || `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')} · Day ${simulation.time?.day ?? '—'}`}</span>
      </div>
      {selectedBuilding&&<aside className="settlement-player-building"><button type="button" onClick={()=>setSelectedBuilding(null)} aria-label="Close">×</button><strong>{selectedBuilding.name}</strong><span>{selectedBuilding.business_type||selectedBuilding.building_type||'Building'}</span>{selectedBuilding.description&&<p>{selectedBuilding.description}</p>}<small>{selectedBuilding.owner_name?`Owner: ${selectedBuilding.owner_name}`:'Owner unknown'} · {(selectedBuilding.rooms||[]).length} rooms</small></aside>}
    </div>
  );
}
