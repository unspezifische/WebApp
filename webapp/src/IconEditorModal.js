import React, { useEffect, useRef, useState } from 'react';
import { Button, Form, Modal, Spinner } from 'react-bootstrap';
import './IconEditorModal.css';

const PREVIEW_BOX = 320;
const OUTPUT_SIZES = [128, 256, 512, 1024];
const FRAME_STYLES = [
  { key: 'none',   label: 'None' },
  { key: 'square', label: 'Square border' },
  { key: 'circle', label: 'Circle' },
  { key: 'ornate', label: 'Ornate' },
];

export default function IconEditorModal({ show, onClose, onUpload, disabled }) {
  const [sourceImage, setSourceImage] = useState(null);
  const [fileName, setFileName] = useState('');
  const [crop, setCrop] = useState(null);
  const [outputSize, setOutputSize] = useState(512);
  const [frameStyle, setFrameStyle] = useState('none');
  const [resultBlob, setResultBlob] = useState(null);
  const [resultUrl, setResultUrl] = useState(null);
  const [working, setWorking] = useState(false);

  const dragRef = useRef(null);

  useEffect(() => {
    if (!show) {
      setSourceImage(null);
      setCrop(null);
      setResultBlob(null);
      setFileName('');
      setWorking(false);
      if (resultUrl) URL.revokeObjectURL(resultUrl);
      setResultUrl(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show]);

  const dispScale = sourceImage
    ? PREVIEW_BOX / Math.max(sourceImage.width, sourceImage.height)
    : 1;
  const dispW = sourceImage ? sourceImage.width * dispScale : 0;
  const dispH = sourceImage ? sourceImage.height * dispScale : 0;
  const offsetX = (PREVIEW_BOX - dispW) / 2;
  const offsetY = (PREVIEW_BOX - dispH) / 2;

  const previewCrop = crop
    ? {
        left: offsetX + crop.x * dispScale,
        top: offsetY + crop.y * dispScale,
        size: crop.size * dispScale,
      }
    : null;

  const onFileChange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        setSourceImage(img);
        const minDim = Math.min(img.width, img.height);
        setCrop({ x: (img.width - minDim) / 2, y: (img.height - minDim) / 2, size: minDim });
        setResultBlob(null);
        if (resultUrl) { URL.revokeObjectURL(resultUrl); setResultUrl(null); }
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  const startPointer = (mode) => (e) => {
    if (!sourceImage || !crop) return;
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { mode, startX: e.clientX, startY: e.clientY, startCrop: { ...crop } };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d || !sourceImage) return;
    const dx = (e.clientX - d.startX) / dispScale;
    const dy = (e.clientY - d.startY) / dispScale;
    const W = sourceImage.width;
    const H = sourceImage.height;

    if (d.mode === 'move') {
      const x = Math.max(0, Math.min(W - d.startCrop.size, d.startCrop.x + dx));
      const y = Math.max(0, Math.min(H - d.startCrop.size, d.startCrop.y + dy));
      setCrop({ x, y, size: d.startCrop.size });
    } else if (d.mode === 'resize') {
      const delta = Math.max(dx, dy);
      const maxByOrigin = Math.min(W - d.startCrop.x, H - d.startCrop.y);
      let size = d.startCrop.size + delta;
      size = Math.max(32, Math.min(maxByOrigin, size));
      setCrop({ x: d.startCrop.x, y: d.startCrop.y, size });
    }
  };

  const onPointerUp = () => {
    dragRef.current = null;
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
  };

  const generateResult = () => {
    if (!sourceImage || !crop) return null;
    const S = outputSize;
    const canvas = document.createElement('canvas');
    canvas.width = S;
    canvas.height = S;
    const ctx = canvas.getContext('2d');
    const isRound = frameStyle === 'circle' || frameStyle === 'ornate';

    if (isRound) {
      ctx.fillStyle = '#1b2430';
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.save();
    if (isRound) {
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2);
      ctx.clip();
    }
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(sourceImage, crop.x, crop.y, crop.size, crop.size, 0, 0, S, S);
    ctx.restore();

    const m = Math.max(4, Math.floor(S * 0.04));
    if (frameStyle === 'square') {
      ctx.strokeStyle = '#3a2b14';
      ctx.lineWidth = m;
      ctx.strokeRect(m / 2, m / 2, S - m, S - m);
      ctx.strokeStyle = '#d8c47a';
      ctx.lineWidth = Math.max(2, m / 3);
      ctx.strokeRect(m, m, S - 2 * m, S - 2 * m);
    } else if (frameStyle === 'circle') {
      ctx.strokeStyle = '#3a2b14';
      ctx.lineWidth = m;
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2 - m / 2, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = '#d8c47a';
      ctx.lineWidth = Math.max(2, m / 3);
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2 - m, 0, Math.PI * 2);
      ctx.stroke();
    } else if (frameStyle === 'ornate') {
      ctx.strokeStyle = '#3a2b14';
      ctx.lineWidth = m;
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2 - m / 2, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = '#d8c47a';
      ctx.lineWidth = Math.max(2, m / 2);
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2 - m, 0, Math.PI * 2);
      ctx.stroke();
      const corner = m * 2;
      ctx.strokeStyle = '#d8c47a';
      ctx.lineWidth = Math.max(2, m / 2);
      [[0, 0], [S, 0], [0, S], [S, S]].forEach(([cx, cy]) => {
        const dx = cx === 0 ? 1 : -1;
        const dy = cy === 0 ? 1 : -1;
        ctx.beginPath();
        ctx.moveTo(cx + dx * corner, cy);
        ctx.lineTo(cx, cy);
        ctx.lineTo(cx, cy + dy * corner);
        ctx.stroke();
      });
    }

    return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  };

  const handleGenerate = async () => {
    if (!sourceImage || !crop) return;
    setWorking(true);
    try {
      const blob = await generateResult();
      if (blob) {
        setResultBlob(blob);
        if (resultUrl) URL.revokeObjectURL(resultUrl);
        setResultUrl(URL.createObjectURL(blob));
      }
    } finally {
      setWorking(false);
    }
  };

  const handleUpload = async () => {
    if (!resultBlob || disabled) return;
    const named = new Blob([resultBlob], { type: resultBlob.type || 'image/png' });
    await onUpload(named);
  };

  return (
    <Modal show={show} onHide={disabled ? () => {} : onClose} size="lg" centered>
      <Modal.Header closeButton>
        <Modal.Title>Design your campaign icon</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <div className="icon-editor-layout">
          <div className="icon-editor-step">
            <h4>1 · Choose an image</h4>
            <Form.Group>
              <Form.Control
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={onFileChange}
              />
            </Form.Group>
            {sourceImage ? (
              <p className="icon-editor-meta">{fileName} · {sourceImage.width}×{sourceImage.height}px</p>
            ) : (
              <p className="icon-editor-meta">PNG, JPEG, WebP, or GIF.</p>
            )}
          </div>

          <div className="icon-editor-step">
            <h4>2 · Crop to a square</h4>
            {sourceImage ? (
              <div className="icon-crop-stage" style={{ width: PREVIEW_BOX, height: PREVIEW_BOX }}>
                <img
                  src={sourceImage.src}
                  alt="Crop source"
                  style={{
                    width: dispW,
                    height: dispH,
                    position: 'absolute',
                    left: offsetX,
                    top: offsetY,
                    pointerEvents: 'none',
                    userSelect: 'none',
                  }}
                  draggable={false}
                />
                <div
                  className="icon-crop-mask"
                  style={{
                    left: previewCrop.left - previewCrop.size,
                    top: previewCrop.top - previewCrop.size,
                    width: previewCrop.size * 3,
                    height: previewCrop.size * 3,
                  }}
                />
                <div
                  className="icon-crop-box"
                  style={{
                    left: previewCrop.left,
                    top: previewCrop.top,
                    width: previewCrop.size,
                    height: previewCrop.size,
                    cursor: 'move',
                  }}
                  onPointerDown={startPointer('move')}
                >
                  <div
                    className="icon-crop-handle"
                    style={{ cursor: 'nwse-resize' }}
                    onPointerDown={startPointer('resize')}
                    title="Drag to resize"
                  />
                </div>
                <div className="icon-crop-dim">Drag to move · Corner to resize</div>
              </div>
            ) : (
              <p className="icon-editor-meta">Choose an image above to begin cropping.</p>
            )}
          </div>

          <div className="icon-editor-step">
            <h4>3 · Resize & frame</h4>
            <Form.Group>
              <Form.Label>Output size (px)</Form.Label>
              <Form.Select
                value={outputSize}
                onChange={(e) => setOutputSize(Number(e.target.value))}
              >
                {OUTPUT_SIZES.map((s) => (
                  <option key={s} value={s}>{s} × {s}</option>
                ))}
              </Form.Select>
            </Form.Group>
            <Form.Group>
              <Form.Label>Frame</Form.Label>
              <Form.Select
                value={frameStyle}
                onChange={(e) => setFrameStyle(e.target.value)}
              >
                {FRAME_STYLES.map((f) => (
                  <option key={f.key} value={f.key}>{f.label}</option>
                ))}
              </Form.Select>
            </Form.Group>
            <Button
              variant="primary"
              onClick={handleGenerate}
              disabled={!sourceImage || working}
              style={{ marginTop: 8 }}
            >
              {working ? 'Generating…' : 'Generate preview'}
            </Button>
          </div>

          <div className="icon-editor-step icon-editor-step-preview">
            <h4>4 · Preview & upload</h4>
            <div className="icon-preview-pane">
              {resultUrl ? (
                <img src={resultUrl} alt="Result preview" style={{ width: 160, height: 160 }} />
              ) : (
                <div className="icon-preview-placeholder">
                  {working ? <Spinner size="sm" /> : 'No preview yet'}
                </div>
              )}
            </div>
            <p className="icon-editor-meta">{outputSize}×{outputSize}px · {resultBlob ? `${(resultBlob.size / 1024).toFixed(1)} KB` : '—'}</p>
          </div>
        </div>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onClose} disabled={disabled}>Cancel</Button>
        <Button
          variant="primary"
          onClick={handleUpload}
          disabled={!resultBlob || disabled}
        >
          {disabled ? 'Uploading…' : 'Save as campaign icon'}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}