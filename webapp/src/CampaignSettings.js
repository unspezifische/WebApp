import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Alert, Badge, Button, Card, Form, Modal, Spinner } from 'react-bootstrap';

import IconEditorModal from './IconEditorModal';
import './CampaignSettings.css';

export default function CampaignSettings({ campaignID, headers, embedded = false }) {
  const [settings,setSettings] = useState(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('');
  const [showAdd,setShowAdd] = useState(false)
  const [selectedKey,setSelectedKey]=useState('')
  const [preview,setPreview] = useState(null);
  const [settlementStrategy,setSettlementStrategy] = useState('merge')
  const [calendarStrategy,setCalendarStrategy] = useState('keep_current');
  const [installing,setInstalling] = useState(false)
  const [notice,setNotice] = useState('');
  const [iconSaving,setIconSaving] = useState(false)
  // const [iconInputKey,setIconInputKey] = useState(0);
  const [iconModalOpen,setIconModalOpen] = useState(false);
  const [rulesetSaving,setRulesetSaving] = useState(false);
  const [campaignName,setCampaignName] = useState('')
  const [nameSaving,setNameSaving]=useState(false);
  const [refreshingModule,setRefreshingModule] = useState('');

  const loadSettings=useCallback(async()=>{
    setLoading(true);setError('');
    try{const response=await axios.get(`/api/campaigns/${campaignID}/modules`,{headers});setSettings(response.data);}
    catch(requestError){setError(requestError.response?.data?.message||'Unable to load campaign settings');}
    finally{setLoading(false);}
  },[campaignID,headers]);

  useEffect(()=>{loadSettings();},[loadSettings]);
  useEffect(()=>{setCampaignName(settings?.campaign?.name||'');},[settings?.campaign?.name]);
  const installable=useMemo(()=>settings?.available_modules?.filter(module=>!module.installed)||[],[settings]);

  const previewModule=useCallback(async(moduleKey)=>{
    setSelectedKey(moduleKey);setPreview(null);setError('');
    if(!moduleKey)return;
    try{
      const response=await axios.post(`/api/campaigns/${campaignID}/modules/preview`,{module_key:moduleKey},{headers});
      setPreview(response.data);
      setSettlementStrategy('merge');
      setCalendarStrategy(response.data.calendar.exists?'keep_current':'use_module');
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to preview module');}
  },[campaignID,headers]);

  const openAddModule=()=>{
    setNotice('');setError('');setShowAdd(true);
    const first=installable[0]?.key||'';
    if(first)previewModule(first);
  };

  const installModule=async()=>{
    if(!selectedKey)return;
    setInstalling(true);setError('');
    try{
      const response=await axios.post(`/api/campaigns/${campaignID}/modules`,{
        module_key:selectedKey,settlement_strategy:settlementStrategy,calendar_strategy:calendarStrategy,
      },{headers});
      setNotice(`${response.data.installation.module_name} installed. Settlement: ${response.data.settlement_result}.`);
      setShowAdd(false);setPreview(null);setSelectedKey('');await loadSettings();
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to install module');}
    finally{setInstalling(false);}
  };

  const refreshModule = async (module) => {
    setRefreshingModule(module.module_key); setError(''); setNotice('');
    try {
      const response = await axios.post(
        `/api/campaigns/${campaignID}/modules/${module.module_key}/refresh`,
        { settlement_strategy: 'merge' },
        { headers },
      );

      const { npcs_added, wiki_pages_added, settlement_result, settlement_name } = response.data;
      const summaryParts = [];

      // 1. Process NPCs breakdown
      if (npcs_added > 0) {
        summaryParts.push(`${npcs_added} new NPC${npcs_added === 1 ? '' : 's'}`);
      }

      // 2. Process Wiki Pages breakdown
      if (wiki_pages_added > 0) {
        summaryParts.push(`${wiki_pages_added} wiki page${wiki_pages_added === 1 ? '' : 's'}`);
      }

      // 3. Process Settlement Map breakdown
      if (settlement_result && settlement_result !== 'none') {
        const actionMap = {
          created: 'imported',
          merged: 'merged',
          overridden: 'overridden'
        };
        const actionWord = actionMap[settlement_result] || 'updated';
        summaryParts.push(`the "${settlement_name || 'Settlement'}" map was ${actionWord}`);
      }

      // 4. Construct the final announcement notice sentence
      if (summaryParts.length > 0) {
        // Formats nicely: "Item A, Item B, and Item C added/updated."
        const lastPart = summaryParts.pop();
        const localizedList = summaryParts.length > 0
          ? `${summaryParts.join(', ')}, and ${lastPart}`
          : lastPart;

        setNotice(`${module.module_name} refreshed. Changes applied: ${localizedList}.`);
      } else {
        setNotice(`${module.module_name} refreshed. Everything was already up to date!`);
      }

      await loadSettings();
    } catch (requestError) {
      setError(requestError.response?.data?.message || 'Unable to refresh module content');
    } finally {
      setRefreshingModule('');
    }
  };

  const replaceCampaign=(campaign)=>setSettings(current=>({...current,campaign}));

  const chooseCampaignIcon=async(presetKey)=>{
    setIconSaving(true);setError('');setNotice('');
    try{
      const response=await axios.patch(`/api/campaigns/${campaignID}/profile-icon`,{preset_key:presetKey},{headers});
      replaceCampaign(response.data.campaign);setNotice('Campaign profile icon updated.');
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to update the campaign icon');}
    finally{setIconSaving(false);}
  };

  const uploadCampaignIcon=async(processedBlob)=>{
    if(!processedBlob)return;
    setIconSaving(true);setError('');setNotice('');
    try{
      const iconFile=new File([processedBlob],`campaign-icon-${Date.now()}.png`,{type:processedBlob.type||'image/png'});
      const body=new FormData();body.append('icon',iconFile);
      const response=await axios.post(`/api/campaigns/${campaignID}/profile-icon`,body,{headers});
      replaceCampaign(response.data.campaign);setNotice('Campaign profile icon uploaded.');
      setIconModalOpen(false);
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to upload the campaign icon');}
    finally{setIconSaving(false);}
  };

  const resetCampaignIcon=async()=>{
    setIconSaving(true);setError('');setNotice('');
    try{
      const response=await axios.patch(`/api/campaigns/${campaignID}/profile-icon`,{reset:true},{headers});
      replaceCampaign(response.data.campaign);setNotice('Campaign profile icon reset.');
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to reset the campaign icon');}
    finally{setIconSaving(false);}
  };

  const chooseRuleset=async(ruleset)=>{
    setRulesetSaving(true);setError('');setNotice('');
    try{
      const response=await axios.patch(`/api/campaigns/${campaignID}/ruleset`,{ruleset},{headers});
      replaceCampaign(response.data.campaign);
      window.dispatchEvent(new CustomEvent('campaign-ruleset-updated',{detail:response.data.campaign}));
      setNotice(`Campaign ruleset changed to ${ruleset}.`);
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to update the campaign ruleset');}
    finally{setRulesetSaving(false);}
  };

  const saveCampaignName=async(event)=>{
    event.preventDefault();
    const name=campaignName.trim();
    if(!name){setError('Campaign name is required.');return;}
    setNameSaving(true);setError('');setNotice('');
    try{
      const response=await axios.patch(`/api/campaigns/${campaignID}/name`,{name},{headers});
      replaceCampaign(response.data.campaign);
      window.dispatchEvent(new CustomEvent('campaign-updated',{detail:response.data.campaign}));
      setNotice(`Campaign renamed to ${response.data.campaign.name}.`);
    }catch(requestError){setError(requestError.response?.data?.message||'Unable to rename the campaign');}
    finally{setNameSaving(false);}
  };

  if(loading)return <div className="campaign-settings-state"><Spinner animation="border"/> Loading campaign settings…</div>;

  return <section className={`campaign-settings-page${embedded?' is-embedded':''}`}>
    {!embedded&&<header><div><span>CAMPAIGN MANAGEMENT</span><h1>{settings?.campaign?.name}</h1><p>Install adventures without discarding the campaign’s accumulated world state.</p></div></header>}
    {error&&<Alert variant="danger" dismissible onClose={()=>setError('')}>{error}</Alert>}
    {notice&&<Alert variant="success" dismissible onClose={()=>setNotice('')}>{notice}</Alert>}

    <div className="campaign-settings-grid">
      <Card className="settings-card campaign-profile-card"><Card.Body>
        <span>CAMPAIGN PROFILE</span><h2>Campaign details</h2>
        <Form className="campaign-name-editor" onSubmit={saveCampaignName}>
          <Form.Group controlId="campaignNameSetting"><Form.Label>Campaign name</Form.Label><Form.Control type="text" value={campaignName} onChange={event=>setCampaignName(event.target.value)} maxLength={100} disabled={nameSaving}/><Form.Text>This changes the display name and wiki URL, while campaign data remains linked by its internal ID.</Form.Text></Form.Group>
          <Button type="submit" disabled={nameSaving||!campaignName.trim()||campaignName.trim()===settings?.campaign?.name}>{nameSaving?'Saving…':'Save name'}</Button>
        </Form>
        <h3 className="campaign-profile-subheading">Profile icon</h3>
        <div className="campaign-icon-editor">
          <div className="campaign-icon-current"><img src={settings?.campaign?.icon||'/sea_turtle_icon_512.png'} alt="Current campaign icon"/><small>Shown on the Account Profile page</small></div>
          <div className="campaign-icon-options">
            <strong>Preloaded icons</strong>
            <div className="campaign-icon-presets">{(settings?.profile_icon_presets||[]).map(preset=><button type="button" key={preset.key} className={settings?.campaign?.icon===preset.url?'selected':''} onClick={()=>chooseCampaignIcon(preset.key)} disabled={iconSaving} aria-label={`Use ${preset.name} campaign icon`}><img src={preset.url} alt=""/><span>{preset.name}</span></button>)}</div>
            <div className="campaign-icon-actions">
              <Button variant="outline-primary" size="sm" onClick={()=>setIconModalOpen(true)} disabled={iconSaving}>Edit & Upload</Button>
              <Button variant="outline-secondary" size="sm" onClick={resetCampaignIcon} disabled={iconSaving||!settings?.campaign?.icon}>Use default</Button>
              {iconSaving&&<span><Spinner size="sm"/> Saving…</span>}
            </div>
          </div>
        </div>

        <IconEditorModal
          show={iconModalOpen}
          onClose={()=>setIconModalOpen(false)}
          onUpload={uploadCampaignIcon}
          disabled={iconSaving}
        />
      </Card.Body></Card>

      <Card className="settings-card"><Card.Body>
        <span>GAME RULES</span><h2>D&amp;D ruleset</h2>
        <p className="settings-card-description">Choose the edition used for character options, rules content, tables, and equipment presets.</p>
        <Form.Group controlId="campaignRulesetSetting"><Form.Label>Edition</Form.Label><Form.Select value={settings?.campaign?.ruleset||'5e'} onChange={event=>chooseRuleset(event.target.value)} disabled={rulesetSaving}>
          <option value="3.5e">3.5e</option>
          <option value="4e">4e</option>
          <option value="5e">5e</option>
          <option value="5e (2024)">5e (2024)</option>
        </Form.Select><Form.Text>System: D&amp;D{rulesetSaving?' · Saving…':''}</Form.Text></Form.Group>
      </Card.Body></Card>

      <Card className="settings-card"><Card.Body>
        <div className="settings-card-title"><div><span>MODULES</span><h2>Installed adventures</h2></div><Button onClick={openAddModule} disabled={!installable.length}>Add module</Button></div>
        {!settings?.installed_modules?.length?<p className="settings-empty">No module installation history is recorded yet.</p>:
          <div className="module-list">{settings.installed_modules.map(module=><article key={module.id}>
            <div><strong>{module.module_name}</strong><small>{module.setting_key?.replaceAll('_',' ')} · module year {module.starting_year??'unspecified'}</small></div>
            <div className="module-list-actions"><Badge bg="secondary">{module.settlement_strategy}</Badge><Button variant="outline-secondary" size="sm" onClick={()=>refreshModule(module)} disabled={!!refreshingModule}>{refreshingModule===module.module_key?'Refreshing…':'Refresh content'}</Button></div>
          </article>)}</div>}
        {!installable.length&&<small>All currently available modules are installed.</small>}
      </Card.Body></Card>

      <Card className="settings-card"><Card.Body>
        <span>IN-WORLD CALENDAR</span><h2>{settings?.calendar?.name||'Not configured'}</h2>
        {settings?.calendar?<dl><div><dt>Format</dt><dd>{settings.calendar.format_slug}</dd></div><div><dt>Current year</dt><dd>{settings.calendar.current_year}</dd></div><div><dt>Date</dt><dd>Month {settings.calendar.current_month_index+1}, day {settings.calendar.current_day}</dd></div></dl>:<p className="settings-empty">Installing a setting module will configure its calendar.</p>}
      </Card.Body></Card>
    </div>

    <Modal show={showAdd} onHide={()=>!installing&&setShowAdd(false)} size="lg" centered>
      <Modal.Header closeButton><Modal.Title>Add module</Modal.Title></Modal.Header>
      <Modal.Body className="module-import-modal">
        <Form.Group><Form.Label>Module</Form.Label><Form.Select value={selectedKey} onChange={event=>previewModule(event.target.value)}>
          {installable.map(module=><option key={module.key} value={module.key}>{module.name}</option>)}
        </Form.Select></Form.Group>
        {!preview&&selectedKey&&<div className="campaign-settings-state"><Spinner size="sm"/> Checking campaign conflicts…</div>}
        {preview&&<>
          <p>{preview.module.description}</p>
          <div className="module-facts"><span>{preview.module.setting_name}</span><span>{preview.module.starting_year_label||`Year ${preview.module.starting_year}`}</span><span>{preview.module.calendar?.name}</span></div>
          {preview.calendar.year_mismatch&&<Alert variant="warning">
            You are currently in year <strong>{preview.calendar.current_year}</strong>, but this module is set in year <strong>{preview.calendar.module_year}</strong>. How should the timeline be reconciled?
          </Alert>}
          {preview.calendar.format_mismatch&&<Alert variant="warning">The campaign currently uses <strong>{preview.calendar.current_format}</strong>, while this module uses <strong>{preview.calendar.module_format}</strong>.</Alert>}
          <Form.Group><Form.Label>Calendar</Form.Label><Form.Select value={calendarStrategy} onChange={event=>setCalendarStrategy(event.target.value)}>
            <option value="keep_current" disabled={!preview.calendar.exists}>Keep the current campaign date</option>
            <option value="use_module">Use the module calendar and move to year {preview.calendar.module_year}</option>
          </Form.Select></Form.Group>
          {!!preview.settlement_conflicts.length&&<Alert variant="info">This module includes {preview.settlement_conflicts.map(conflict=>conflict.incoming_name).join(', ')}, which already exists in the campaign.</Alert>}
          {preview.settlement_template_available?<Form.Group><Form.Label>Existing settlements</Form.Label><Form.Select value={settlementStrategy} onChange={event=>setSettlementStrategy(event.target.value)}>
            <option value="merge">Merge additions into the current maps</option>
            <option value="keep">Keep current maps and import only non-map content</option>
            <option value="override">Replace conflicting settlement maps with module versions</option>
          </Form.Select><Form.Text>Merging retains existing records and adds module features whose stable IDs or names are new.</Form.Text></Form.Group>:<Alert variant="secondary">This module currently provides calendar and campaign content but no packaged settlement map.</Alert>}
        </>}
      </Modal.Body>
      <Modal.Footer><Button variant="secondary" onClick={()=>setShowAdd(false)} disabled={installing}>Cancel</Button><Button onClick={installModule} disabled={!preview||installing}>{installing?'Installing…':'Install module'}</Button></Modal.Footer>
    </Modal>
  </section>;
}
