import React, { useCallback, useEffect, useState, useMemo, useRef } from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation, useNavigate } from 'react-router-dom';
import io from 'socket.io-client';
import { Container, Row, Col, Alert, Button, Spinner, Modal } from 'react-bootstrap';
import axios from 'axios';

import UserContext from './UserContext';
import Login from './Login';
import Register from './Register';

import Menu from './Menu';
import DMTools from './DMTools';
import SettlementManager from './SettlementManager';
import SettlementPlayerView from './SettlementPlayerView';
import WorldAtlas from './WorldAtlas';
import CharacterSheet from './CharacterSheet';
import InventoryView from './InventoryView';
import Journal from './Journal';
import Library from './Library';
import Calendar from './Calendar';
import AccountProfile from './AccountProfile';
import Chat from './Chat';
import ChatIcon from '@mui/icons-material/Chat';
import { DMSoundPlayerBar, DMSoundPlayerProvider } from './DMSoundPlayer';

import './App.css';
import 'bootstrap/dist/css/bootstrap.min.css';
import { IconButton, Badge } from '@mui/material';

const EMPTY_CAMPAIGN = { id: null, name: null, dmId: null, ownerId: null };

function entrySearchParams() {
  const direct = new URLSearchParams(window.location.search);
  if (direct.get('campaignID') || !direct.get('redirect')) return direct;
  try {
    const target = new URL(direct.get('redirect'), window.location.origin);
    return target.origin === window.location.origin ? target.searchParams : direct;
  } catch (_error) {
    return direct;
  }
}

function loginEntryPath() {
  if (window.location.pathname === '/login') return '/login';
  const target = `${window.location.pathname}${window.location.search}`;
  return `/login?redirect=${encodeURIComponent(target)}`;
}

function isSettlementPath(pathname) {
  return pathname === '/settlementManager' || pathname === '/maps/player' || pathname === '/worldAtlas';
}

function CampaignLayout({ menuProps, children }) {
  const location = useLocation();
  const isMapPage = isSettlementPath(location.pathname);
  const hideMenu = isMapPage || location.pathname === '/accountProfile';

  return (
    <div className={`app-layout${isMapPage ? ' map-page-layout' : ''}`}>
      {!hideMenu && (
        <aside className="menu-column">
          <Menu {...menuProps} />
        </aside>
      )}
      <main className="content-column">{children}</main>
    </div>
  );
}

function HideOnSettlementRoutes({ children }) {
  const location = useLocation();
  return isSettlementPath(location.pathname) || location.pathname === '/accountProfile' ? null : children;
}

function SoundPlayerCornerBar({ workspaceActive, onOpen }) {
  const navigate = useNavigate();
  const location = useLocation();
  const fullPlayerVisible = workspaceActive && location.pathname === '/dmTools';

  return (
    <DMSoundPlayerBar
      hidden={fullPlayerVisible}
      quickFxConfigurable={fullPlayerVisible}
      onExpand={() => {
        onOpen();
        navigate('/dmTools');
      }}
    />
  );
}

function CampaignSoundProvider({ headers, socket, enabled, children }) {
  const location = useLocation();
  return (
    <DMSoundPlayerProvider headers={headers} socket={socket} enabled={enabled && !isSettlementPath(location.pathname)}>
      {children}
    </DMSoundPlayerProvider>
  );
}

function loadStoredCampaign() {
  const params = entrySearchParams();
  const sharedCampaignId = Number(params.get('campaignID'));
  if (Number.isInteger(sharedCampaignId) && sharedCampaignId > 0) {
    return { ...EMPTY_CAMPAIGN, id:sharedCampaignId, name:params.get('campaignName') || 'Campaign' };
  }
  if (!localStorage.getItem('token') || !localStorage.getItem('accountType')) {
    return EMPTY_CAMPAIGN;
  }

  try {
    const stored = JSON.parse(localStorage.getItem('selectedCampaign') || 'null');
    return stored?.id ? { ...EMPTY_CAMPAIGN, ...stored } : EMPTY_CAMPAIGN;
  } catch (error) {
    console.warn('Unable to restore the selected campaign:', error);
    return EMPTY_CAMPAIGN;
  }
}

function App() {
  const SOCKET_URL = window.location.origin;
  const isMapsHost = /^maps\./i.test(window.location.hostname);
  const primaryHostname = window.location.hostname.replace(/^(?:app|maps|mtg|tools)\./i, '');
  const primaryOrigin = `${window.location.protocol}//${primaryHostname}${window.location.port ? `:${window.location.port}` : ''}`;
  const dmLandingPath = isMapsHost ? '/settlementManager' : '/dmTools';

  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark');

  // High-level Chat states
  const [showChat, setShowChat] = useState(false);
  const [chatUsers, setChatUsers] = useState([]);
  const [chatMessages, setChatMessages] = useState([]);
  const [unreadMessages, setUnreadMessages] = useState(0);
  const [soundWorkspaceActive, setSoundWorkspaceActive] = useState(false);
  const [soundPlayerOpenRequest, setSoundPlayerOpenRequest] = useState(0);

  // User and session states
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [username, setUsername] = useState('');
  const [userID, setUserID] = useState(null);
  const [character, setCharacter] = useState(null);
  const [characterName, setCharacterName] = useState(localStorage.getItem('characterName') || '');
  const [characterID, setCharacterID] = useState(null);
  const [accountType, setAccountType] = useState(localStorage.getItem('accountType') || entrySearchParams().get('accountType') || '');

  const [isLoading, setIsLoading] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [selectedCampaign, setSelectedCampaign] = useState(loadStoredCampaign);

  const socketRef = useRef(null);
  const [socketLoading, setSocketLoading] = useState(true);
  const [socketConnected, setSocketConnected] = useState(false);
  const [inCombat, setInCombat] = useState(false);

  const [initiativeOrder, setInitiativeOrder] = useState(0);
  const [currentTurn, setCurrentTurn] = useState(1);
  const [show, setShow] = useState(false);
  const [turnInfo, setTurnInfo] = useState({ current: null, next: null });
  const [combatants, setCombatants] = useState([]);

  const resetCampaignSelection = useCallback(() => {
    setSelectedCampaign(EMPTY_CAMPAIGN);
    setAccountType('');
    setCharacterName('');
    setCharacterID(null);
    setCharacter(null);
    localStorage.removeItem('selectedCampaign');
    localStorage.removeItem('accountType');
    localStorage.removeItem('characterName');
  }, []);

  const expireSession = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('userID');
    setToken('');
    setIsLoggedIn(false);
    setUsername('');
    setUserID(null);
    resetCampaignSelection();
  }, [resetCampaignSelection]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    if (selectedCampaign?.id && accountType) {
      localStorage.setItem('selectedCampaign', JSON.stringify(selectedCampaign));
      localStorage.setItem('accountType', accountType);
      localStorage.setItem('characterName', characterName || '');
    } else {
      localStorage.removeItem('selectedCampaign');
      localStorage.removeItem('accountType');
      localStorage.removeItem('characterName');
    }
  }, [selectedCampaign, accountType, characterName]);

  useEffect(() => {
    const updateSelectedCampaign = (event) => {
      const campaign = event.detail;
      if (!campaign?.id) return;
      setSelectedCampaign(current => current?.id === campaign.id ? {
        ...current,
        name: campaign.name ?? current.name,
        ruleset: campaign.ruleset,
        rulesSystem: campaign.rules_system,
      } : current);
    };
    window.addEventListener('campaign-updated', updateSelectedCampaign);
    window.addEventListener('campaign-ruleset-updated', updateSelectedCampaign);
    return () => {
      window.removeEventListener('campaign-updated', updateSelectedCampaign);
      window.removeEventListener('campaign-ruleset-updated', updateSelectedCampaign);
    };
  }, []);

  useEffect(() => {
    if (selectedCampaign.id && accountType === 'Player') {
      axios.get(`/api/character`, { headers })
        .then((res) => {
          setCharacter(res.data);
          const resolvedName = res.data?.Name || res.data?.name || res.data?.character_name || '';
          setCharacterName(resolvedName);
          setCharacterID(res.data?.id ?? null);
        })
        .catch((err) => console.error(err));
    }
  }, [selectedCampaign, accountType]);

  const headers = useMemo(() => ({
    Authorization: `Bearer ${token}`,
    userID,
    username,
    characterID,
    campaignID: selectedCampaign.id,
    ...(selectedCampaign.rulesSystem ? { System: selectedCampaign.rulesSystem } : {}),
  }), [token, userID, username, selectedCampaign, characterID]);

  useEffect(() => {
    if (!token || !selectedCampaign?.id) {
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
      setSocketConnected(false);
      setSocketLoading(false);
      return;
    }

    setSocketLoading(true);

    const socket = io(SOCKET_URL, {
      path: '/socket.io/',
      // Start with HTTP polling so the app remains usable behind proxies that
      // cannot complete a WebSocket upgrade, then upgrade when available.
      transports: ['polling', 'websocket'],
      query: {
        token,
        campaignID: selectedCampaign.id,
      },
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 2000,
      autoConnect: true,
    });

    socketRef.current = socket;

    const handleConnect = () => {
      setSocketConnected(true);
      setSocketLoading(false);

      if (username && selectedCampaign?.id) {
        socket.emit('join_room', {
          username,
          campaign_id: selectedCampaign.id,
        });
      }
    };

    const handleConnectError = (error) => {
      console.error('Socket Connection Error:', error);
      setSocketConnected(false);
      setSocketLoading(false);
    };

    const handleDisconnect = (reason) => {
      console.warn('Socket Disconnected:', reason);
      setSocketConnected(false);

      if (reason === 'io server disconnect') {
        socket.connect();
      }
    };

    const handleTokenExpired = () => {
      expireSession();
    };

    const handleRequestCampaignID = () => {
      if (selectedCampaign?.id) {
        socket.emit('send_campaignID', { campaignID: selectedCampaign.id });
      }
    };

    socket.on('connect', handleConnect);
    socket.on('connect_error', handleConnectError);
    socket.on('disconnect', handleDisconnect);
    socket.on('token_expired', handleTokenExpired);
    socket.on('request_campaignID', handleRequestCampaignID);

    return () => {
      socket.off('connect', handleConnect);
      socket.off('connect_error', handleConnectError);
      socket.off('disconnect', handleDisconnect);
      socket.off('token_expired', handleTokenExpired);
      socket.off('request_campaignID', handleRequestCampaignID);
      socket.disconnect();

      if (socketRef.current === socket) {
        socketRef.current = null;
      }

      setSocketConnected(false);
    };
  }, [token, selectedCampaign?.id, username, expireSession]);

  useEffect(() => {
    const socket = socketRef.current;
    if (!socket || !socketConnected || !selectedCampaign?.id || !username) return;

    socket.emit('join_room', {
      username,
      campaign_id: selectedCampaign.id,
    });
  }, [socketConnected, selectedCampaign?.id, username]);

  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;

    const handleTurnUpdate = ({ current, next }) => {
      setCurrentTurn(current.order);
      setTurnInfo((prevState) => ({
        ...prevState,
        current,
        next,
      }));
    };

    const handleEndOfCombat = () => setInCombat(false);

    const updateCombatants = (combatants) => {
      setCombatants(combatants);

      const yourSpot =
        combatants.findIndex(
          (combatant) => combatant.characterName === characterName
        ) + 1;

      if (combatants.length >= 2) {
        const current = { character: combatants[0], order: 1 };
        const next = { character: combatants[1], order: 2 };
        setTurnInfo({ current, next, yourSpot });
      }
    };

    const handleRollForInitiative = () => setShow(true);

    socket.on('Roll for initiative!', handleRollForInitiative);
    socket.on('combatants', updateCombatants);
    socket.on('turn update', handleTurnUpdate);
    socket.on('end of combat', handleEndOfCombat);

    return () => {
      socket.off('Roll for initiative!', handleRollForInitiative);
      socket.off('combatants', updateCombatants);
      socket.off('turn update', handleTurnUpdate);
      socket.off('end of combat', handleEndOfCombat);
    };
  }, [socketConnected, characterName]);


  // Chat message handling and active users
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket || !socketConnected || !selectedCampaign?.id) return;

    const handleActiveUsers = (activeUsers) => {
      setChatUsers(activeUsers.filter(user => user.username !== username));
    };

    const handleMessage = (incomingMessage) => {
      const isRelevant =
        incomingMessage.sender === userID ||
        incomingMessage.recipients?.includes(userID);

      if (!isRelevant) return;

      setChatMessages(prev => [...prev, incomingMessage]);

      if (!showChat) {
        setUnreadMessages(prev => prev + 1);
      }
    };

    socket.on('active_users', handleActiveUsers);
    socket.on('message', handleMessage);

    socket.emit('request_active_users', { campaignID: selectedCampaign.id });

    return () => {
      socket.off('active_users', handleActiveUsers);
      socket.off('message', handleMessage);
    };
  }, [socketConnected, selectedCampaign?.id, username, userID, showChat]);

  const handleInitiativeSubmit = () => {
    socketRef.current.emit('initiative roll', { characterName, roll: initiativeOrder });
    setShow(false);
    setInCombat(true);
  };

  useEffect(() => {
      if (showChat) {
        setUnreadMessages(0);
      }
    }, [showChat]);

  return (
    <UserContext.Provider value={{ characterName, accountType, headers, setIsLoggedIn, socket: socketRef.current }}>
      <Router>
        {isLoading && (
          <div className="app-spinner-wrap">
            <Spinner animation="border" role="status" />
          </div>
        )}

        {show && accountType === 'Player' && (
          <Alert variant="danger" onClose={() => setShow(false)} className="initiative-alert">
            <Alert.Heading>Roll for Initiative!</Alert.Heading>
            <input
              type="number"
              value={initiativeOrder}
              onChange={(e) => setInitiativeOrder(e.target.value)}
            />
            <Button onClick={handleInitiativeSubmit}>Submit</Button>
          </Alert>
        )}

        {isLoggedIn ? (
          selectedCampaign.id ? (
            <Container fluid className="app-shell">
              <CampaignSoundProvider headers={headers} socket={socketRef.current} enabled={accountType === 'DM'}>
              <CampaignLayout
                menuProps={{
                  headers,
                  accountType,
                  selectedCampaign,
                  setSelectedCampaign,
                  theme,
                  setTheme,
                  primaryOrigin,
                }}
              >
                  {inCombat && accountType !== 'DM' && turnInfo.current?.character?.characterName && turnInfo.next?.character?.characterName && (
                    <div className="combat-banner">
                      <strong>Current:</strong> {turnInfo.current.character.characterName} ({turnInfo.current.order}){' '}
                      <strong>Next:</strong> {turnInfo.next.character.characterName} ({turnInfo.next.order}){' '}
                      <strong>You:</strong> {turnInfo.yourSpot}
                    </div>
                  )}

                  <Routes>
                    <Route path="/" element={<Navigate to={dmLandingPath} />} />
                    <Route path="/characterSheet" element={<CharacterSheet headers={headers} characterName={characterName} setCharacterName={setCharacterName} />} />
                    <Route path="/dmTools" element={<DMTools headers={headers} socket={socketRef.current} accountType={accountType} onSoundWorkspaceChange={setSoundWorkspaceActive} soundPlayerOpenRequest={soundPlayerOpenRequest} />} />
                    <Route
                      path="/settlementManager"
                      element={
                        accountType === 'DM'
                          ? <SettlementManager headers={headers} socket={socketRef.current} mainEnvironmentUrl={`${primaryOrigin}/dmTools`} />
                          : <Navigate to="/accountProfile" replace />
                      }
                    />
                    <Route path="/maps/player" element={<SettlementPlayerView headers={headers} socket={socketRef.current} />} />
                    <Route path="/worldAtlas" element={accountType === 'DM' ? <WorldAtlas headers={headers} socket={socketRef.current} mainEnvironmentUrl={`${primaryOrigin}/dmTools`} /> : <Navigate to="/characterSheet" replace />} />
                    <Route path="/inventoryView" element={<InventoryView username={username} characterName={characterName} accountType={accountType} headers={headers} socket={socketRef.current} campaignID={selectedCampaign.id} isLoading={isLoading} setIsLoading={setIsLoading} />} />
                    <Route path="/journal" element={<Journal characterName={characterName} headers={headers} isLoading={isLoading} campaignID={selectedCampaign.id} theme={theme} />} />
                    <Route path="/library" element={<Library headers={headers} socket={socketRef.current} />} />
                    <Route path="/calendar" element={<Calendar headers={headers} socket={socketRef.current} characterName={characterName} username={username} accountType={accountType} campaignID={selectedCampaign.id} />} />
                    <Route path="/campaignSettings" element={<Navigate to={accountType === 'DM' ? '/dmTools' : '/characterSheet'} replace />} />
                    <Route path="/accountProfile" element={<AccountProfile headers={headers} setAccountType={setAccountType} setCharacterName={setCharacterName} setSelectedCampaign={setSelectedCampaign} dmLandingPath={dmLandingPath} primaryOrigin={primaryOrigin} />} />
                    <Route path="*" element={<Navigate to={accountType === 'DM' ? dmLandingPath : '/characterSheet'} replace />} />
                  </Routes>
              </CampaignLayout>

              {accountType === 'DM' && (
                <HideOnSettlementRoutes>
                  <SoundPlayerCornerBar
                    workspaceActive={soundWorkspaceActive}
                    onOpen={() => setSoundPlayerOpenRequest((requestNumber) => requestNumber + 1)}
                  />
                </HideOnSettlementRoutes>
              )}

              {/* Chat FAB and Modal */}
              <HideOnSettlementRoutes><div className="chat-fab-wrap">
                <Badge
                  badgeContent={unreadMessages > 99 ? '99+' : unreadMessages}
                  color="error"
                  overlap="circular"
                  anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
                  invisible={unreadMessages === 0}
                  className="chat-fab-badge"
                >
                  <IconButton
                    className="chat-fab"
                    onClick={() => setShowChat(true)}
                    aria-label="Open chat"
                  >
                    <ChatIcon />
                  </IconButton>
                </Badge>
              </div></HideOnSettlementRoutes>
              

              <Modal
                show={showChat}
                onHide={() => setShowChat(false)}
                dialogClassName="chat-modal"
                contentClassName="chat-modal-content"
                centered
              >
                <Modal.Header closeButton>
                  <Modal.Title>Whisper</Modal.Title>
                </Modal.Header>
                <Modal.Body className="chat-modal-body">
                  {!socketLoading && (
                    <Chat
                      headers={headers}
                      socket={socketRef.current}
                      characterName={characterName}
                      username={username}
                      campaignID={selectedCampaign.id}
                      users={chatUsers}
                      messages={chatMessages}
                      setMessages={setChatMessages}
                      requestActiveUsers={() => socketRef.current?.emit('request_active_users', { campaignID: selectedCampaign.id })}
                    />
                  )}
                </Modal.Body>
              </Modal>
              </CampaignSoundProvider>
            </Container>
          ) : (
            <Routes>
              <Route
                path="/accountProfile"
                element={
                  <AccountProfile
                    headers={headers}
                    setSelectedCampaign={setSelectedCampaign}
                    setCharacterName={setCharacterName}
                    setAccountType={setAccountType}
                    dmLandingPath={dmLandingPath}
                    primaryOrigin={primaryOrigin}
                  />
                }
              />
              <Route path="*" element={<Navigate to="/accountProfile" replace />} />
            </Routes>
          )
        ) : (
          <Container fluid>
            <Routes>
              <Route path="/login" element={<Login setIsLoggedIn={setIsLoggedIn} setToken={setToken} setUserID={setUserID} setIsLoading={setIsLoading} setAppUsername={setUsername} resetCampaignSelection={resetCampaignSelection} expireSession={expireSession} />} />
              <Route path="/register" element={<Register setIsLoggedIn={setIsLoggedIn} setToken={setToken} setAppUsername={setUsername} setUserID={setUserID} />} />
              <Route
                path="*"
                element={
                  token
                    ? <Login setIsLoggedIn={setIsLoggedIn} setToken={setToken} setUserID={setUserID} setIsLoading={setIsLoading} setAppUsername={setUsername} resetCampaignSelection={resetCampaignSelection} expireSession={expireSession} />
                    : <Navigate to={loginEntryPath()} replace />
                }
              />
            </Routes>
          </Container>
        )}
      </Router>
    </UserContext.Provider>
  );
}

export default App;
