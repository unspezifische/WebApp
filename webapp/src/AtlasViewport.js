import React, { useRef, useState } from 'react';
import PublicIcon from '@mui/icons-material/Public';

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

export default function AtlasViewport({ atlas, locations = [], selectedId, onSelect, onPlace, placementEnabled = false, draftMarker = null }) {
  const viewportRef = useRef(null), gestureRef = useRef(null);
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const tileZoom = Number(atlas?.tile_zoom ?? 2), tileCount = 2 ** tileZoom;
  const tiles = !atlas?.image_url && atlas?.tile_url_template ? Array.from({ length: tileCount * tileCount }, (_, index) => ({ x: index % tileCount, y: Math.floor(index / tileCount) })) : [];
  const constrain = (next, bounds) => ({ ...next, x: clamp(next.x, Math.min(0, bounds.width * (1 - next.zoom)), 0), y: clamp(next.y, Math.min(0, bounds.height * (1 - next.zoom)), 0) });
  const zoomAt = (nextZoom, clientX, clientY) => {
    const bounds = viewportRef.current?.getBoundingClientRect(); if (!bounds) return;
    setView((current) => { const zoom = clamp(nextZoom, 1, 8), localX = clientX == null ? bounds.width / 2 : clientX - bounds.left, localY = clientY == null ? bounds.height / 2 : clientY - bounds.top, worldX = (localX - current.x) / current.zoom, worldY = (localY - current.y) / current.zoom; return constrain({ zoom, x: localX - worldX * zoom, y: localY - worldY * zoom }, bounds); });
  };
  const pointerDown = (event) => { if (event.button !== 0 || event.target.closest('.atlas-marker,.atlas-viewport-controls')) return; gestureRef.current = { id: event.pointerId, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, dragged: false }; event.currentTarget.setPointerCapture?.(event.pointerId); };
  const pointerMove = (event) => { const gesture = gestureRef.current; if (!gesture || gesture.id !== event.pointerId) return; const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y; if (Math.hypot(event.clientX - gesture.startX, event.clientY - gesture.startY) > 4) gesture.dragged = true; gesture.x = event.clientX; gesture.y = event.clientY; if (gesture.dragged) { const bounds = viewportRef.current.getBoundingClientRect(); setView((current) => constrain({ ...current, x: current.x + dx, y: current.y + dy }, bounds)); } };
  const pointerUp = (event) => { const gesture = gestureRef.current; if (!gesture || gesture.id !== event.pointerId) return; gestureRef.current = null; if (!gesture.dragged && placementEnabled && onPlace) { const bounds = viewportRef.current.getBoundingClientRect(); onPlace(clamp((event.clientX - bounds.left - view.x) / (bounds.width * view.zoom), 0, 1), clamp((event.clientY - bounds.top - view.y) / (bounds.height * view.zoom), 0, 1)); } };
  return <div ref={viewportRef} className={`atlas-map atlas-viewport ${atlas?.image_url ? 'has-image' : ''} ${placementEnabled ? 'placing-new' : ''}`} onWheel={(event) => { event.preventDefault(); zoomAt(view.zoom * Math.exp(-event.deltaY * .0015), event.clientX, event.clientY); }} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { gestureRef.current = null; }} role="application" aria-label="Overworld atlas map">
    <div className="atlas-map-content" style={{ backgroundImage: atlas?.image_url ? `url(${atlas.image_url})` : undefined, transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` }}>
      {!!tiles.length && <div className="atlas-tiles" style={{ gridTemplateColumns: `repeat(${tileCount},1fr)` }}>{tiles.map((tile) => <img key={`${tile.x}-${tile.y}`} src={atlas.tile_url_template.replace('{z}', tileZoom).replace('{x}', tile.x).replace('{y}', tile.y)} alt="" draggable="false"/>)}</div>}
      {!atlas?.image_url && !tiles.length && <div className="atlas-empty"><PublicIcon/><strong>{atlas?.name || 'Campaign World'}</strong><span>Add a world atlas image, or use the blank coordinate space.</span></div>}
      {locations.filter((item) => item.atlas_x != null && item.atlas_y != null).map((item) => <button type="button" key={item.id} className={`atlas-marker ${item.id === selectedId ? 'active' : ''} ${item.status === 'destroyed' ? 'destroyed' : ''}`} style={{ left: `${item.atlas_x * 100}%`, top: `${item.atlas_y * 100}%` }} onClick={(event) => { event.stopPropagation(); onSelect?.(item.id); }}><i/><span>{item.name}{item.status === 'destroyed' ? ' · Destroyed' : ''}</span></button>)}
      {draftMarker?.atlas_x != null && <div className="atlas-draft-marker" style={{ left: `${draftMarker.atlas_x * 100}%`, top: `${draftMarker.atlas_y * 100}%` }}><i/><span>{draftMarker.name || 'New settlement'}</span></div>}
    </div>
    <div className="atlas-viewport-controls"><button type="button" onClick={() => zoomAt(view.zoom / 1.35)} aria-label="Zoom out">−</button><span>{Math.round(view.zoom * 100)}%</span><button type="button" onClick={() => zoomAt(view.zoom * 1.35)} aria-label="Zoom in">+</button><button type="button" onClick={() => setView({ zoom: 1, x: 0, y: 0 })}>Fit</button></div>
    <small className="atlas-navigation-hint">Wheel to zoom · drag to pan{placementEnabled ? ' · click to place marker' : ''}</small>
  </div>;
}
