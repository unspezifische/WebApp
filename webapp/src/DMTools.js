import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Modal, Form, ListGroup } from 'react-bootstrap';
import { Table, InputGroup, FormControl } from 'react-bootstrap';
import { Container, Row, Col } from 'react-bootstrap';

import axios from 'axios';

import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';

import Inventory2Icon from '@mui/icons-material/Inventory2';
import CasinoIcon from '@mui/icons-material/Casino';
import GroupsIcon from '@mui/icons-material/Groups';
import BadgeIcon from '@mui/icons-material/Badge';
import SportsKabaddiIcon from '@mui/icons-material/SportsKabaddi';
import MusicNoteIcon from '@mui/icons-material/MusicNote';
import SettingsIcon from '@mui/icons-material/Settings';
import HistoryIcon from '@mui/icons-material/History';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';

import './DMTools.css';
import { DMSoundPlayerWorkspace } from './DMSoundPlayer';
import CampaignSettings from './CampaignSettings';

const alignments = ['Any Alignment', 'Any Good Alignment', 'Lawful Good', 'Neutral Good', 'Chaotic Good', 'Lawful Neutral', 'Neutral', 'Chaotic Neutral', 'Lawful Evil', 'Neutral Evil', 'Chaotic Evil', 'Any Non-good Alignment'];

const NPC_COLUMNS = [
  { key: 'name', label: 'Name', defaultVisible: true },
  { key: 'creature_type', label: 'Type', defaultVisible: true },
  { key: 'size', label: 'Size', defaultVisible: false },
  { key: 'alignment', label: 'Alignment', defaultVisible: false },
  { key: 'challenge', label: 'CR', defaultVisible: true },
  { key: 'ac', label: 'AC', defaultVisible: true },
  { key: 'hp', label: 'HP', defaultVisible: true },
  { key: 'speed', label: 'Speed', defaultVisible: false },
  { key: 'strength', label: 'STR', defaultVisible: false },
  { key: 'dexterity', label: 'DEX', defaultVisible: false },
  { key: 'constitution', label: 'CON', defaultVisible: false },
  { key: 'intelligence', label: 'INT', defaultVisible: false },
  { key: 'wisdom', label: 'WIS', defaultVisible: false },
  { key: 'charisma', label: 'CHA', defaultVisible: false },
];
const NPC_COLUMN_STORAGE_KEY = 'kachhapa-npc-library-columns';

const initialNpcColumns = () => {
  try {
    const stored = JSON.parse(window.localStorage.getItem(NPC_COLUMN_STORAGE_KEY));
    if (Array.isArray(stored)) {
      const valid = stored.filter((key) => NPC_COLUMNS.some((column) => column.key === key));
      if (valid.length) return valid;
    }
  } catch (error) {
    // Ignore unavailable or malformed local preferences.
  }
  return NPC_COLUMNS.filter((column) => column.defaultVisible).map((column) => column.key);
};

const npcChallengeValue = (value) => {
  const token = String(value ?? '').trim().split(/\s+/)[0];
  if (token.includes('/')) {
    const [numerator, denominator] = token.split('/').map(Number);
    return denominator ? numerator / denominator : 0;
  }
  return Number(token) || 0;
};

const InputFormGroup = ({ label, type, value, onChange, name, placeholder }) => (
  <Form.Group>
    <Form.Label>{label}</Form.Label>
    <Form.Control
      as={type === 'textarea' ? 'textarea' : 'input'}
      rows={type === 'textarea' ? 3 : undefined} // Add rows attribute for textarea
      value={value}
      placeholder={placeholder || ''}  // Adds a placeholder with a default empty string
      onChange={onChange}
      name={name}
    />
  </Form.Group>
);

const catalogScopeLabel = (record, modules) => {
  const moduleName = modules.find(module => module.module_key === record.module_key)?.module_name || record.module_key;
  if (record.scope === 'module_preset') return `${moduleName || 'Module'} preset`;
  if (record.scope === 'system_preset') return `${record.system || 'System'} preset`;
  return moduleName ? `Campaign · ${moduleName}` : 'Campaign';
};

function DMTools({ headers, socket, characterName, accountType, onSoundWorkspaceChange, soundPlayerOpenRequest }) {
  const navigate = useNavigate();

  useEffect(() => {
    if (accountType?.toLowerCase() === 'player') {
      navigate('/characterSheet');
    }
  }, [accountType, navigate]);

  const [lootBoxes, setLootBoxes] = useState([]);
  const [catalogModules, setCatalogModules] = useState([]);
  const [currentContent, setCurrentContent] = useState('lootBoxes'); // State to control what to display in the second Col

  useEffect(() => {
    onSoundWorkspaceChange?.(currentContent === 'soundPlayer');
  }, [currentContent, onSoundWorkspaceChange]);

  useEffect(() => () => onSoundWorkspaceChange?.(false), [onSoundWorkspaceChange]);

  useEffect(() => {
    if (soundPlayerOpenRequest) setCurrentContent('soundPlayer');
  }, [soundPlayerOpenRequest]);

  const [npcs, setNpcs] = useState([]);
  const [npcSearch, setNpcSearch] = useState('');
  const [npcSort, setNpcSort] = useState({ key: 'name', direction: 'asc' });
  const [npcVisibleColumns, setNpcVisibleColumns] = useState(initialNpcColumns);
  const [npcModalOpen, setNpcModalOpen] = useState(false);
  const [npcData, setNpcData] = useState({
    name: '',
    size: '',
    creatureType: '',
    creatureSubtype: '',
    alignment: '',
    ac: '',
    hp: '',
    speed: '',
    strength: '',
    dexterity: '',
    constitution: '',
    intelligence: '',
    wisdom: '',
    charisma: '',
    skills: '',
    senses: '',
    languages: '',
    challenge: '',
    traits: '',
    actions: '',
    description: ''
  });

  const [selectedNpc, setSelectedNpc] = useState(null);

  useEffect(() => {
    window.localStorage.setItem(NPC_COLUMN_STORAGE_KEY, JSON.stringify(npcVisibleColumns));
  }, [npcVisibleColumns]);

  const displayedNpcs = useMemo(() => {
    const query = npcSearch.trim().toLocaleLowerCase();
    const matching = npcs.filter((npc) => !query || Object.values(npc)
      .filter((value) => value !== null && value !== undefined)
      .some((value) => String(value).toLocaleLowerCase().includes(query)));

    return [...matching].sort((left, right) => {
      const key = npcSort.key;
      let comparison;
      if (key === 'challenge') {
        comparison = npcChallengeValue(left[key]) - npcChallengeValue(right[key]);
      } else if (['speed', 'strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma'].includes(key)) {
        comparison = Number(left[key] || 0) - Number(right[key] || 0);
      } else {
        comparison = String(left[key] ?? '').localeCompare(String(right[key] ?? ''), undefined, { numeric: true, sensitivity: 'base' });
      }
      return npcSort.direction === 'desc' ? -comparison : comparison;
    });
  }, [npcSearch, npcSort, npcs]);

  const toggleNpcColumn = (key) => {
    setNpcVisibleColumns((current) => current.includes(key)
      ? (current.length > 1 ? current.filter((column) => column !== key) : current)
      : [...current, key]);
  };

  const sortNpcColumn = (key) => {
    setNpcSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'asc' ? 'desc' : 'asc',
    }));
  };


  // Define a function to fetch players
  const fetchPlayers = () => {
    console.log('fetchPlayers called');

    axios.get('/api/players', { headers: headers })
      .then((response) => {
        console.log('DM TOOLS- players:', response.data.players);
        setPlayers(response.data.players);
      })
      .catch((error) => {
        console.error('Failed to fetch players:', error.response.data);
      });
  };

  // Define a function to fetch loot boxes
  const fetchLootBoxes = () => {
    axios.get('/api/lootboxes', { headers: headers })
      .then((response) => {
        // console.log('DM TOOLS- loot boxes:', response.data.lootBoxes);
        setLootBoxes(response.data.lootBoxes);
        setCatalogModules(response.data.modules || []);
      })
      .catch((error) => {
        console.error('Failed to fetch loot boxes:', error.response.data);
      });
  };

  // Fetch lootboxes when the component mounts
  useEffect(() => {
    fetchPlayers();
    fetchLootBoxes();
  }, []);

  const [lootBoxModalOpen, setLootBoxModalOpen] = useState(false);
  const [lootBoxName, setLootBoxName] = useState('');
  const [lootBoxModuleKey, setLootBoxModuleKey] = useState('');
  const [items, setItems] = useState([]);
  const [searchText, setSearchText] = useState('');
  const [selectedItems, setSelectedItems] = useState([]);

  const [players, setPlayers] = useState([]);
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [selectedLootBox, setSelectedLootBox] = useState({ items: [] });
  const [viewLootBoxModal, setViewLootBoxModal] = useState(false);
  const [editingLootBoxId, setEditingLootBoxId] = useState(null);

  const [inventory, setInventory] = useState([]);
  const [viewPlayerInventoryModal, setViewPlayerInventoryModal] = useState(false);
  const [currentTurn, setCurrentTurn] = useState(0);
  const [combatants, setCombatants] = useState([]);
  const [encounterRound, setEncounterRound] = useState(1);
  const [encounterStarted, setEncounterStarted] = useState(false);
  const [encounterSearch, setEncounterSearch] = useState('');

  // Loot Box Functions
  const handleShowLootBoxes = () => {
    setCurrentContent('lootBoxes');
    fetchLootBoxes();
  };

  const handleCreateLootBox = () => {
    setEditingLootBoxId(null);
    setLootBoxName('');
    setLootBoxModuleKey('');
    setSelectedItems([]);
    axios
      .get('/api/items', { headers: headers })
      .then(response => {
        console.log('Items from API:', response.data.items);
        setItems(response.data.items);
      })
      .catch(error => console.error('Error fetching items:', error));
    setLootBoxModalOpen(true);
  };

  const handleItemClick = item => {
    setSelectedItems(prevItems => [...prevItems, { ...item, quantity: 1 }]);
  };

  const handleItemQuantityChange = (itemId, quantity) => {
    setSelectedItems(prevItems => {
      const newItems = [...prevItems];
      const itemIndex = newItems.findIndex(item => item.id === itemId);
      newItems[itemIndex].quantity = quantity;
      return newItems;
    });
  };

  const handleItemSearchChange = e => {
    setSearchText(e.target.value);
  };

  const handleItemRemoveClick = item => {
    setSelectedItems(prevItems => prevItems.filter(i => i.id !== item.id));
  };

  const handleLootBoxClick = lootBox => {
    if (lootBox.editable === false) return;
    // fetchPlayers();
    setSelectedItems(lootBox.items);
    setLootBoxName(lootBox.name);
    setLootBoxModuleKey(lootBox.module_key || '');
    setEditingLootBoxId(lootBox.id); // Remember which loot box we are editing
    setLootBoxModalOpen(true);
  };

  const handleSaveLootBox = () => {
    const items = selectedItems.map(item => ({ id: item.id, quantity: item.quantity }));

    if (editingLootBoxId === null) {
      // If we are not currently editing a loot box, create a new one
      axios
        .post('/api/lootboxes', { name: lootBoxName, items: items, module_key: lootBoxModuleKey || null }, { headers: headers })
        .then(response => {
          console.log(response.data.message);
          setLootBoxModalOpen(false);
          setLootBoxName('');
          setLootBoxModuleKey('');
          setSelectedItems([]);
          fetchLootBoxes(); // Fetch the updated list of loot boxes
        })
        .catch(error => console.error('Error saving loot box:', error));
    } else {
      // If we are editing a loot box, update it
      axios
        .put(`/api/lootboxes/${editingLootBoxId}`, { name: lootBoxName, items: items, module_key: lootBoxModuleKey || null }, { headers: headers })
        .then(response => {
          console.log(response.data.message);
          setLootBoxModalOpen(false);
          setLootBoxName('');
          setLootBoxModuleKey('');
          setSelectedItems([]);
          setEditingLootBoxId(null); // Clear the editing state
          fetchLootBoxes(); // Fetch the updated list of loot boxes
        })
        .catch(error => console.error('Error updating loot box:', error));
    }
  };

  const viewLootBox = (lootBox) => {
    fetchPlayers(); // Get the currently online players cause we're gonna need that in the modal which opens
    console.log("Getting details for loot box:", lootBox)
    if (Array.isArray(lootBox.items)) {
      setSelectedLootBox(lootBox);
      setViewLootBoxModal(true);
      return;
    }
    axios.get(`/api/lootboxes/${lootBox.id}`, { headers: headers })
    .then(response => {
      console.log('Opening LootBox:', response.data.items);
      const items = response.data.items;
      setSelectedLootBox({ ...lootBox, items: items });
      setViewLootBoxModal(true);
    })
    .catch(error => console.error('Error fetching loot box items:', error));
  };

  const editLootBox = () => {
    setLootBoxName(selectedLootBox.name); // Add this line
    setSelectedItems(selectedLootBox.items); // Add this line
    setLootBoxModuleKey(selectedLootBox.module_key || '');
    setEditingLootBoxId(selectedLootBox.id); // So we can update an existing loot box
    setLootBoxModalOpen(true);
    setViewLootBoxModal(false);
  };

  const deleteLootBox = (lootBox) => {
    axios.delete(`/api/lootboxes/${lootBox.id}`, { headers: headers })
    .then(response => {
      console.log(response.data.message);
      setLootBoxes(current => current.filter(candidate => candidate.id !== lootBox.id));
    })
    .catch(error => console.error('Error deleting loot box:', error))
    .finally(() => setViewLootBoxModal(false));
  }

  const issueLootToPlayer = (lootBox) => {
    console.log("Issuing", lootBox, "to", selectedPlayer);
    // Issue items via API call to /api/lootboxes/<int:box_id>
    axios.post(`/api/lootboxes/${lootBox.id}`, { player: selectedPlayer }, { headers: headers })
    // axios.post(`/api/lootboxes/${lootBox.id}`, { player: selectedPlayer })
    .then(response => {
      console.log(response.data.message);
      setSelectedPlayer(null); // Clear the selected player
      fetchLootBoxes(); // Fetch the updated list of loot boxes
    })
    .catch(error => console.error('Error issuing loot box:', error))
    .finally(setViewLootBoxModal(false));
  };

  // View Player Inventories
  const handleShowPlayerInventories = () => {
    setCurrentContent('playerInventories'); // Set the state to show player inventories
    fetchPlayers(); // Get the currently online players cause we're gonna need that in the modal which opens
  };

  const viewPlayerInventory = (player) => {
    // API call to get player's inventory
    axios.get('/api/inventory', {
      headers: {
        ...headers,
        'Character-Name': player.character_name, // Include the character name in the request headers
        'Character-ID': player.id
      }})
      .then(response => {
        console.log("Getting inventory for " + player.character_name);
        setInventory(response.data.inventory);
        setSelectedPlayer(player);
        setViewPlayerInventoryModal(true);
      })
      .catch(error => console.error('Error fetching inventory:', error));
  }

  // Initiative Tracker
  const [newEntry, setNewEntry] = useState({ characterName: '', initiative: '' });  // State for new entry
  const sortCombatants = (entries) => [...entries].sort(
    (a, b) => (Number(b.initiative) || -Infinity) - (Number(a.initiative) || -Infinity)
  );

  // Handle input changes for new entry
  const handleNewEntryChange = (field, value) => {
    setNewEntry(prevEntry => ({ ...prevEntry, [field]: value }));
  };

  // Handle submission of new entry
  const handleNewEntrySubmit = () => {
    const name = newEntry.characterName.trim();
    if (!name || newEntry.initiative === '') return;

    setCombatants(prevCombatants => {
      return sortCombatants([
        ...prevCombatants,
        {
          id: `custom-${Date.now()}`,
          characterName: name,
          initiative: Number(newEntry.initiative),
          kind: 'custom',
        },
      ]);
    });
    // Clear the new entry fields
    setNewEntry({ characterName: '', initiative: '' });
  };

  useEffect(() => {
    if (socket == null) return;
    
    // setCombatants([]) // Will this ensure the list is clear when initiative starts?

    const handleInitiativeRoll = ({ characterName, roll }) => {
      console.log("characterName - roll:", characterName + "-" + roll);
      setCombatants((prevCombatants) => {
        const existingIndex = prevCombatants.findIndex(
          (combatant) => combatant.characterName === characterName
        );
        const updated = [...prevCombatants];
        const rolledCombatant = {
          ...(existingIndex >= 0 ? updated[existingIndex] : {}),
          id: existingIndex >= 0 ? updated[existingIndex].id : `player-roll-${characterName}`,
          characterName,
          initiative: Number(roll),
          kind: existingIndex >= 0 ? updated[existingIndex].kind : 'player',
        };

        if (existingIndex >= 0) updated[existingIndex] = rolledCombatant;
        else updated.push(rolledCombatant);
        return sortCombatants(updated);
      });
    };

    socket.on('initiative roll', handleInitiativeRoll);

    return () => {
      socket.off('initiative roll', handleInitiativeRoll);
    };
  }, [socket]);

  useEffect(() => {
    if (socket == null) return;

    socket.emit('combatants', combatants);
    console.log("combatants:", combatants);
  }, [combatants, socket])

  const handleInitiative = () => {
    setCurrentContent('initiative');
    if (socket) socket.emit("Roll for initiative!");
  };

  const handleNextButtonClick = () => {
    if (combatants.length === 0) return;

    const nextTurn = (currentTurn + 1) % combatants.length;
    if (nextTurn === 0) setEncounterRound((round) => round + 1);
    setCurrentTurn(nextTurn);

    const current = { character: combatants[nextTurn], order: nextTurn + 1 };
    const followingIndex = (nextTurn + 1) % combatants.length;
    const next = { character: combatants[followingIndex], order: followingIndex + 1 };

    if (socket) socket.emit('update turn', { current, next });
  };

  const handleEndOfCombat = () => {
    setCombatants([]); // Reset the combatants
    setCurrentTurn(0); // Reset the current turn
    setEncounterRound(1);
    setEncounterStarted(false);
    if (socket) socket.emit('end of combat'); // Notify players
  };

  const addEncounterCombatant = (entry) => {
    setCombatants((current) => {
      if (current.some((combatant) => combatant.id === entry.id)) return current;
      return [...current, entry];
    });
  };

  const addPlayerToEncounter = (player) => {
    addEncounterCombatant({
      id: `player-${player.id ?? player.character_name}`,
      sourceId: player.id,
      characterName: player.character_name,
      initiative: '',
      kind: 'player',
    });
  };

  const addNpcToEncounter = (npc) => {
    addEncounterCombatant({
      id: `npc-${npc.id}-${Date.now()}`,
      sourceId: npc.id,
      characterName: npc.name,
      initiative: '',
      kind: 'npc',
      ac: npc.ac,
      hp: npc.hp,
      dexterity: npc.dexterity,
    });
  };

  const removeEncounterCombatant = (combatantId) => {
    setCombatants((current) => current.filter((combatant) => combatant.id !== combatantId));
    setCurrentTurn(0);
  };

  const setEncounterInitiative = (combatantId, value) => {
    setCombatants((current) => current.map((combatant) => (
      combatant.id === combatantId
        ? { ...combatant, initiative: value === '' ? '' : Number(value) }
        : combatant
    )));
  };

  const rollNpcInitiative = (combatantId) => {
    setCombatants((current) => current.map((combatant) => {
      if (combatant.id !== combatantId) return combatant;
      const dexterity = Number(combatant.dexterity) || 10;
      const modifier = Math.floor((dexterity - 10) / 2);
      return {
        ...combatant,
        initiative: Math.floor(Math.random() * 20) + 1 + modifier,
      };
    }));
  };

  const requestPlayerInitiative = () => {
    if (socket) socket.emit('Roll for initiative!');
  };

  const beginEncounter = () => {
    if (combatants.length === 0) return;
    const orderedCombatants = sortCombatants(combatants);
    setCombatants(orderedCombatants);
    setCurrentTurn(0);
    setEncounterRound(1);
    setEncounterStarted(true);

    if (socket) {
      socket.emit('combatants', orderedCombatants);
      const nextIndex = orderedCombatants.length > 1 ? 1 : 0;
      socket.emit('update turn', {
        current: { character: orderedCombatants[0], order: 1 },
        next: { character: orderedCombatants[nextIndex], order: nextIndex + 1 },
      });
    }
  };


  // NPC Cards
  const fetchNpcs = (campaignId) => {
    axios.get('/api/npcs', { headers: headers })
      .then(response => {
        setNpcs(response.data);
      })
      .catch(error => {
        console.error('Failed to fetch NPCs:', error.response.data);
      });
  };

  const handleCreateNpc = () => {
    setNpcModalOpen(true);
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    // console.log("name: ", name, "value: ", value);
    setNpcData({
      ...npcData,
      [name]: value
    });
  };

  // useEffect(() => {
  //   console.log('NPC Data:', npcData);
  // }, [npcData]);
  
  const handleSaveNpc = () => {
    console.log('Saving NPC:', npcData);
    const campaignId = headers['CampaignID'];
    const newNpc = {
      campaign_id: campaignId,
      ...npcData
    };
    axios.post('/api/npcs', newNpc, { headers: headers })
      .then(response => {
        console.log('NPC saved successfully:', response.data);
        setNpcs([...npcs, response.data]);
        setNpcModalOpen(false);
        setNpcData({
          name: '',
          size: '',
          creatureType: '',
          creatureSubtype: '',
          alignment: '',
          ac: '',
          hp: '',
          speed: '',
          strength: '',
          dexterity: '',
          constitution: '',
          intelligence: '',
          wisdom: '',
          charisma: '',
          saving_throws: '',
          skills: '',
          immunities: '',
          resistance: '',
          senses: '',
          languages: '',
          challenge: '',
          traits: '',
          actions: '',
          description: ''
        });
      })
      .catch(error => {
        console.error('Failed to save NPC:', error.response.data);
      });
  };

  const handleNpcClick = (npc) => {
    setSelectedNpc(npc);
  };

  const handleShowNPCCards = () => {
    const campaignId = headers['CampaignID'];
    fetchNpcs(campaignId);
    setCurrentContent('npcCards');
  };


  // Random Tables to Roll On
  const [randomTables, setRandomTables] = useState([]);
  const [randomTableData, setRandomTableData] = useState({
    name: '',
    description: '',
    diceType: '',
    moduleKey: '',
    entries: []
  });
  const [randomTableModalOpen, setRandomTableModalOpen] = useState(false);
  const [viewTableModalOpen, setViewTableModalOpen] = useState(false);
  const [selectedTable, setSelectedTable] = useState(null);
  const [selectedTableEntries, setSelectedTableEntries] = useState([]);
  const [isEditing, setIsEditing] = useState(false);

  const [entryMinRoll, setEntryMinRoll] = useState('');
  const [entryMaxRoll, setEntryMaxRoll] = useState('');
  const [entryResult, setEntryResult] = useState('');


  // Fetch random tables from Flask and the database
  const fetchRandomTables = () => {
    axios.get('/api/random_tables', { headers: headers })
      .then(response => {
        console.log("Tables-", response.data);
        setRandomTables(response.data);
      })
      .catch(error => {
        console.error('Failed to fetch random tables:', error.response.data);
      });
  };

  const handleShowRandomTables = () => {
    fetchRandomTables();
    setCurrentContent('Random Tables');
  }

  const handleTableSelect = (table) => {
    console.log("selected: ", table.name);
    axios.get(`/api/random_tables/${table.id}`, { headers: headers })
      .then(response => {
        setSelectedTable(response.data);
        setSelectedTableEntries(response.data.table_entries);
        setViewTableModalOpen(true);
      })
      .catch(error => {
        console.error('Failed to fetch table entries:', error);
      });
  };

  const openCreateTableModal = () => {
    setRandomTableModalOpen(true);
  };

  // Fetch tables on component mount
  useEffect(() => {
    fetchRandomTables();
  }, []);

  // Function to handle table creation or update
  const handleSaveRandomTable = () => {
    if (isEditing) {
      // Update existing table
      axios.put(`/api/random_tables/${selectedTable.id}`, randomTableData, { headers: headers })
        .then(response => {
          console.log('Table updated successfully:', response.data);
          fetchRandomTables();
          setRandomTableModalOpen(false);
          setRandomTableData({
            name: '',
            description: '',
            diceType: '',
            moduleKey: '',
            entries: []
          });
          setIsEditing(false);
        })
        .catch(error => {
          console.error('Error updating table:', error);
        });
    } else {
      // Create new table
      axios.post('/api/random_tables', randomTableData, { headers: headers })
        .then(response => {
          console.log('Table created successfully:', response.data);
          fetchRandomTables();
          setRandomTableModalOpen(false);
          setRandomTableData({
            name: '',
            description: '',
            diceType: '',
            moduleKey: '',
            entries: []
          });
        })
        .catch(error => {
          console.error('Error creating table:', error);
        });
    }
  };

  // Function to handle adding an entry
  const handleAddEntry = () => {
    const newEntry = {
      min_roll: entryMinRoll,
      max_roll: entryMaxRoll,
      result: entryResult
    };
    setRandomTableData(prevData => ({
      ...prevData,
      entries: [...prevData.entries, newEntry]
    }));
    setEntryMinRoll('');
    setEntryMaxRoll('');
    setEntryResult('');
  };

  // Function to handle removing an entry
  const handleRemoveEntry = (index) => {
    setRandomTableData(prevData => ({
      ...prevData,
      entries: prevData.entries.filter((_, i) => i !== index)
    }));
  };

  // Function to handle editing a table
  const editRandomTable = () => {
    setViewTableModalOpen(false);
    setRandomTableData({
      name: selectedTable.name,
      description: selectedTable.description,
      diceType: selectedTable.dice_type,
      moduleKey: selectedTable.module_key || '',
      entries: selectedTable.table_entries
    });
    setIsEditing(true);
    setRandomTableModalOpen(true);
  };

  // Function to handle table deletion
  const deleteRandomTable = (tableId) => {
    axios.delete(`/api/random_tables/${tableId}`, { headers: headers })
      .then(response => {
        console.log('Table deleted successfully:', response.data);

        // Fetch the updated list of tables
        fetchRandomTables();

        // Close the view table modal
        setViewTableModalOpen(false);
        setSelectedTable(null);
      })
      .catch(error => {
        console.error('Error deleting table:', error);
      });
  };


  // Transaction History
  const [itemTransfers, setItemTransfers] = useState([]);
  const fetchItemTransfers = () => {
    axios.get('/api/item_transfers')
    .then(response => {
      setItemTransfers(response.data);
    })
    .catch(error => {
      console.error('Failed to fetch item transfers:', error);
    });
  };

  const handleShowTransactionHistory = () => {
    fetchItemTransfers();
    setCurrentContent('Transaction History');
  };

  const TOOL_GROUPS = [
    {
      title: 'Prepare',
      items: [
        {
          id: 'lootBoxes',
          label: 'Loot Boxes',
          description: 'Create, inspect, edit, and assign saved loot packages.',
          icon: <Inventory2Icon fontSize="small" />,
        },
        {
          id: 'npcCards',
          label: 'NPC Library',
          description: 'Create and manage saved NPC cards for this campaign.',
          icon: <BadgeIcon fontSize="small" />,
        },
        {
          id: 'encounterBuilder',
          label: 'Encounter Builder',
          description: 'Build a roster, collect initiative, and run combat turn by turn.',
          icon: <SportsKabaddiIcon fontSize="small" />,
          actionLabel: encounterStarted ? 'Next Turn' : 'Begin Encounter',
          action: encounterStarted ? handleNextButtonClick : beginEncounter,
        },
        {
          id: 'campaignSettings',
          label: 'Campaign Settings',
          description: 'Install campaign modules and reconcile shared world settings.',
          icon: <SettingsIcon fontSize="small" />,
        },
      ],
    },
    {
      title: 'Run',
      items: [
        {
          id: 'soundPlayer',
          label: 'Music Player',
          description: 'Mix looping ambience and music with independent one-shot sound effects.',
          icon: <MusicNoteIcon fontSize="small" />,
        },
        {
          id: 'playerInventories',
          label: 'Player Inventories',
          description: 'Inspect player inventories without changing them directly.',
          icon: <GroupsIcon fontSize="small" />,
          actionLabel: 'Refresh Players',
          action: fetchPlayers,
        },
        {
          id: 'transactionHistory',
          label: 'Transaction History',
          description: 'Review item transfers and table-side activity.',
          icon: <HistoryIcon fontSize="small" />,
          actionLabel: 'Refresh History',
          action: fetchItemTransfers,
        },
        {
          id: 'randomTables',
          label: 'Random Tables',
          description: 'Create and roll on random event and result tables.',
          icon: <CasinoIcon fontSize="small" />,
          actionLabel: 'Add Roll Table',
          action: openCreateTableModal,
        },
        {
          id: 'initiative',
          label: 'Enter Combat',
          description: 'Collect initiative rolls, establish turn order, and enter combat.',
          icon: <SportsKabaddiIcon fontSize="small" />,
          actionLabel: 'Roll for Initiative',
          action: handleInitiative,
        },
      ],
    },
  ];

  const toolLookup = Object.fromEntries(
    TOOL_GROUPS.flatMap((group) => group.items.map((tool) => [tool.id, tool]))
  );

  const activeTool = toolLookup[currentContent] || null;

  const selectTool = (toolId) => {
    switch (toolId) {
      case 'lootBoxes':
        handleShowLootBoxes();
        break;
      case 'playerInventories':
        handleShowPlayerInventories();
        break;
      case 'soundPlayer':
        setCurrentContent('soundPlayer');
        break;
      case 'campaignSettings':
        setCurrentContent('campaignSettings');
        break;
      case 'initiative':
        handleInitiative();
        break;
      case 'npcCards':
        handleShowNPCCards();
        break;
      case 'randomTables':
        handleShowRandomTables();
        break;
      case 'transactionHistory':
        handleShowTransactionHistory();
        break;
      case 'encounterBuilder':
        setCurrentContent('encounterBuilder');
        handleShowBuildEncounter();
        break;
      default:
        setCurrentContent('home');
        break;
    }
  };

  const renderHomeDashboard = () => (
    <div className="dmtools-dashboard">
      <div className="dmtools-dashboard-grid">
        <button className="dmtools-dashboard-card" onClick={handleCreateLootBox}>
          <div className="dmtools-dashboard-card-icon"><Inventory2Icon /></div>
          <div className="dmtools-dashboard-card-title">Create Loot Box</div>
          <div className="dmtools-dashboard-card-text">
            Build a loot package and assign it to a player later.
          </div>
        </button>

        <button className="dmtools-dashboard-card" onClick={handleCreateNpc}>
          <div className="dmtools-dashboard-card-icon"><BadgeIcon /></div>
          <div className="dmtools-dashboard-card-title">Create NPC</div>
          <div className="dmtools-dashboard-card-text">
            Build a reusable NPC card and save it to the campaign.
          </div>
        </button>

        <button className="dmtools-dashboard-card" onClick={handleInitiative}>
          <div className="dmtools-dashboard-card-icon"><SportsKabaddiIcon /></div>
          <div className="dmtools-dashboard-card-title">Enter Combat</div>
          <div className="dmtools-dashboard-card-text">
            Prompt players to roll and begin turn tracking.
          </div>
        </button>

        <button className="dmtools-dashboard-card" onClick={openCreateTableModal}>
          <div className="dmtools-dashboard-card-icon"><CasinoIcon /></div>
          <div className="dmtools-dashboard-card-title">Add Roll Table</div>
          <div className="dmtools-dashboard-card-text">
            Create a random table for events, traits, or encounters.
          </div>
        </button>

        <button className="dmtools-dashboard-card" onClick={() => setCurrentContent('soundPlayer')}>
          <div className="dmtools-dashboard-card-icon"><MusicNoteIcon /></div>
          <div className="dmtools-dashboard-card-title">Open Music Player</div>
          <div className="dmtools-dashboard-card-text">
            Layer background ambience with table-ready sound effects.
          </div>
        </button>
      </div>

      <div className="dmtools-overview-grid">
        <div className="dmtools-overview-panel">
          <div className="dmtools-overview-title">Recent Assets</div>
          <div className="dmtools-overview-list">
            <div className="dmtools-overview-item">
              <span>Loot Boxes</span>
              <strong>{lootBoxes.length}</strong>
            </div>
            <div className="dmtools-overview-item">
              <span>NPC Cards</span>
              <strong>{npcs.length}</strong>
            </div>
            <div className="dmtools-overview-item">
              <span>Random Tables</span>
              <strong>{randomTables.length}</strong>
            </div>
            <div className="dmtools-overview-item">
              <span>Visible Players</span>
              <strong>{players.length}</strong>
            </div>
          </div>
        </div>

        <div className="dmtools-overview-panel">
          <div className="dmtools-overview-title">Quick Start</div>
          <div className="dmtools-overview-copy">
            Select a tool from the rail to open its workspace. Each tool loads into the
            main panel, where you can create, review, and manage campaign assets.
          </div>
        </div>
      </div>
    </div>
  );

  const renderLootBoxes = () => (
    <>
      <div className="dmtools-section-actions">
        <Button onClick={handleCreateLootBox}>Create Loot Box</Button>
      </div>

      <div className="dmtools-table-shell">
        <Table striped bordered hover className="dmtools-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Scope</th>
              <th style={{ width: '180px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {lootBoxes.length === 0 ? (
              <tr>
                <td colSpan={3} className="dmtools-empty-cell">
                  No loot boxes yet.
                </td>
              </tr>
            ) : (
              lootBoxes.map((lootBox, i) => (
                <tr key={i}>
                  <td>{lootBox.name}</td>
                  <td><span className={`catalog-scope ${lootBox.is_preset?'preset':''}`}>{catalogScopeLabel(lootBox,catalogModules)}</span></td>
                  <td>
                    <div className="dmtools-inline-actions">
                      <Button size="sm" variant="primary" onClick={() => viewLootBox(lootBox)}>
                        Examine
                      </Button>
                      {lootBox.editable!==false&&<Button size="sm" variant="outline-light" onClick={() => handleLootBoxClick(lootBox)}>Edit</Button>}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
      </div>
    </>
  );

  const renderPlayerInventories = () => (
    <div className="dmtools-table-shell">
      <Table striped bordered className="dmtools-table">
        <thead>
          <tr>
            <th>Player</th>
            <th style={{ width: '180px' }}>View</th>
          </tr>
        </thead>
        <tbody>
          {players.filter(player => player.id !== null).length === 0 ? (
            <tr>
              <td colSpan={2} className="dmtools-empty-cell">No players found.</td>
            </tr>
          ) : (
            players.filter(player => player.id !== null).map((player, i) => (
              <tr key={i}>
                <td>{player.character_name}</td>
                <td>
                  <Button variant="primary" size="sm" onClick={() => viewPlayerInventory(player)}>
                    Examine
                  </Button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </Table>
    </div>
  );

  const renderInitiative = () => (
    <>
      <div className="dmtools-section-actions">
        <Button onClick={handleNextButtonClick} disabled={combatants.length === 0}>
          Next Turn
        </Button>
        <Button variant="danger" onClick={handleEndOfCombat}>
          End Combat
        </Button>
      </div>

      <div className="dmtools-table-shell">
        <Table bordered className="dmtools-table">
          <thead>
            <tr>
              <th style={{ width: '180px' }}>Initiative</th>
              <th>Character</th>
            </tr>
          </thead>
          <tbody>
            {combatants.map((player, i) => (
              <tr key={i} className={i === currentTurn ? 'table-warning' : ''}>
                <td>{player.initiative}</td>
                <td>{player.characterName}</td>
              </tr>
            ))}
            <tr>
              <td>
                <Form.Control
                  type="number"
                  value={newEntry.initiative}
                  onChange={e => handleNewEntryChange('initiative', e.target.value)}
                />
              </td>
              <td>
                <div className="dmtools-inline-actions">
                  <Form.Control
                    type="text"
                    value={newEntry.characterName}
                    onChange={e => handleNewEntryChange('characterName', e.target.value)}
                  />
                  <Button onClick={handleNewEntrySubmit}>Add</Button>
                </div>
              </td>
            </tr>
          </tbody>
        </Table>
      </div>
    </>
  );

  const renderNpcCards = () => (
    <>
      <div className="dmtools-section-actions">
        <Button onClick={handleCreateNpc}>Create NPC</Button>
      </div>

      <div className="dmtools-library-controls">
        <Form.Control
          type="search"
          aria-label="Search NPC library"
          placeholder="Search names, types, traits, languages…"
          value={npcSearch}
          onChange={(event) => setNpcSearch(event.target.value)}
        />
        <details className="dmtools-column-picker">
          <summary>Columns ({npcVisibleColumns.length})</summary>
          <div>
            {NPC_COLUMNS.map((column) => (
              <label key={column.key}>
                <input
                  type="checkbox"
                  checked={npcVisibleColumns.includes(column.key)}
                  onChange={() => toggleNpcColumn(column.key)}
                />
                {column.label}
              </label>
            ))}
          </div>
        </details>
      </div>

      <div className="dmtools-table-shell">
        <Table striped bordered hover className="dmtools-table">
          <thead>
            <tr>
              {NPC_COLUMNS.filter((column) => npcVisibleColumns.includes(column.key)).map((column) => (
                <th key={column.key}>
                  <button
                    type="button"
                    className={`dmtools-sort-header${npcSort.key === column.key ? ' is-active' : ''}`}
                    onClick={() => sortNpcColumn(column.key)}
                    aria-label={`Sort NPCs by ${column.label}`}
                  >
                    {column.label}
                    {npcSort.key === column.key && <span aria-hidden="true">{npcSort.direction === 'asc' ? '▲' : '▼'}</span>}
                  </button>
                </th>
              ))}
              <th style={{ width: '180px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {displayedNpcs.length === 0 ? (
              <tr>
                <td colSpan={npcVisibleColumns.length + 1} className="dmtools-empty-cell">{npcs.length ? 'No NPCs match that search.' : 'No NPCs saved yet.'}</td>
              </tr>
            ) : (
              displayedNpcs.map((npc) => (
                <tr key={npc.id}>
                  {NPC_COLUMNS.filter((column) => npcVisibleColumns.includes(column.key)).map((column) => (
                    <td key={column.key}>{npc[column.key] ?? '—'}</td>
                  ))}
                  <td>
                    <Button variant="primary" size="sm" onClick={() => handleNpcClick(npc)}>
                      View Actions
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
      </div>
    </>
  );

  const renderRandomTables = () => (
    <>
      <div className="dmtools-section-actions">
        <Button onClick={openCreateTableModal}>Add a Roll Table</Button>
      </div>

      <div className="dmtools-table-shell">
        <Table striped bordered hover className="dmtools-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Scope</th>
              <th style={{ width: '180px' }}>Details</th>
            </tr>
          </thead>
          <tbody>
            {randomTables.length === 0 ? (
              <tr>
                <td colSpan={3} className="dmtools-empty-cell">No roll tables created yet.</td>
              </tr>
            ) : (
              randomTables.map((table, i) => (
                <tr key={i}>
                  <td>{table.name}</td>
                  <td><span className={`catalog-scope ${table.is_preset?'preset':''}`}>{catalogScopeLabel(table,catalogModules)}</span></td>
                  <td>
                    <Button variant="primary" size="sm" onClick={() => handleTableSelect(table)}>
                      Select
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
      </div>
    </>
  );

  const renderTransactionHistory = () => (
    <div className="dmtools-table-shell">
      <Table striped bordered hover className="dmtools-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Sender</th>
            <th>Recipients</th>
            <th>Item</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {itemTransfers.length === 0 ? (
            <tr>
              <td colSpan={5} className="dmtools-empty-cell">No transactions found.</td>
            </tr>
          ) : (
            itemTransfers.map((transfer, i) => (
              <tr key={i}>
                <td>{new Date(transfer.timestamp).toLocaleString()}</td>
                <td>{transfer.sender_id}</td>
                <td>{transfer.recipient_ids.join(', ')}</td>
                <td>{transfer.item_id}</td>
                <td>{transfer.message_text}</td>
              </tr>
            ))
          )}
        </tbody>
      </Table>
    </div>
  );

  const renderEncounterBuilder = () => {
    const normalizedSearch = encounterSearch.trim().toLowerCase();
    const availablePlayers = players.filter((player) => (
      player.id !== null &&
      player.character_name &&
      player.character_name.toLowerCase().includes(normalizedSearch) &&
      !combatants.some((combatant) => combatant.id === `player-${player.id ?? player.character_name}`)
    ));
    const availableNpcs = npcs.filter((npc) => (
      npc.name?.toLowerCase().includes(normalizedSearch)
    ));
    const readyCount = combatants.filter((combatant) => combatant.initiative !== '').length;

    return (
      <div className="encounter-builder">
        <section className="encounter-status" aria-label="Encounter status">
          <div>
            <span className="encounter-kicker">{encounterStarted ? `Round ${encounterRound}` : 'Encounter setup'}</span>
            <h3>
              {encounterStarted && combatants[currentTurn]
                ? `${combatants[currentTurn].characterName}'s turn`
                : `${combatants.length} combatant${combatants.length === 1 ? '' : 's'} ready`}
            </h3>
            <p>
              {encounterStarted
                ? `Up next: ${combatants[(currentTurn + 1) % combatants.length]?.characterName || '—'}`
                : `${readyCount} of ${combatants.length} initiative rolls entered.`}
            </p>
          </div>
          <div className="encounter-status-actions">
            {!encounterStarted ? (
              <>
                <Button variant="outline-primary" onClick={requestPlayerInitiative}>
                  Ask Players to Roll
                </Button>
                <Button onClick={beginEncounter} disabled={combatants.length === 0}>
                  Begin Encounter
                </Button>
              </>
            ) : (
              <>
                <Button onClick={handleNextButtonClick}>Next Turn</Button>
                <Button variant="outline-danger" onClick={handleEndOfCombat}>End Encounter</Button>
              </>
            )}
          </div>
        </section>

        <div className="encounter-layout">
          <aside className="encounter-library">
            <div className="encounter-panel-heading">
              <div>
                <span className="encounter-kicker">Campaign roster</span>
                <h3>Add combatants</h3>
              </div>
            </div>
            <Form.Control
              type="search"
              aria-label="Search campaign roster"
              placeholder="Search players and NPCs"
              value={encounterSearch}
              onChange={(event) => setEncounterSearch(event.target.value)}
            />

            <div className="encounter-library-group">
              <h4>Players</h4>
              {availablePlayers.length === 0 ? (
                <p className="encounter-empty">No matching players to add.</p>
              ) : availablePlayers.map((player) => (
                <button
                  type="button"
                  className="encounter-library-item"
                  key={player.id ?? player.character_name}
                  onClick={() => addPlayerToEncounter(player)}
                >
                  <span>
                    <strong>{player.character_name}</strong>
                    <small>Player character</small>
                  </span>
                  <span aria-hidden="true">＋</span>
                </button>
              ))}
            </div>

            <div className="encounter-library-group">
              <h4>Saved NPCs</h4>
              {availableNpcs.length === 0 ? (
                <p className="encounter-empty">No matching saved NPCs.</p>
              ) : availableNpcs.map((npc) => (
                <button
                  type="button"
                  className="encounter-library-item"
                  key={npc.id}
                  onClick={() => addNpcToEncounter(npc)}
                >
                  <span>
                    <strong>{npc.name}</strong>
                    <small>CR {npc.challenge || '—'} · AC {npc.ac || '—'} · HP {npc.hp || '—'}</small>
                  </span>
                  <span aria-hidden="true">＋</span>
                </button>
              ))}
            </div>
          </aside>

          <section className="encounter-order">
            <div className="encounter-panel-heading">
              <div>
                <span className="encounter-kicker">Initiative order</span>
                <h3>Turn tracker</h3>
              </div>
              <span className="encounter-count">{combatants.length}</span>
            </div>

            {combatants.length === 0 ? (
              <div className="encounter-order-empty">
                <SportsKabaddiIcon />
                <strong>Your encounter is empty</strong>
                <span>Add campaign players or saved NPCs from the roster.</span>
              </div>
            ) : (
              <div className="encounter-combatants">
                {combatants.map((combatant, index) => (
                  <div
                    className={`encounter-combatant ${encounterStarted && index === currentTurn ? 'is-active' : ''}`}
                    key={combatant.id}
                  >
                    <span className="encounter-position">{index + 1}</span>
                    <div className="encounter-combatant-copy">
                      <strong>{combatant.characterName}</strong>
                      <small>
                        {combatant.kind === 'npc'
                          ? `NPC${combatant.ac ? ` · AC ${combatant.ac}` : ''}${combatant.hp ? ` · HP ${combatant.hp}` : ''}`
                          : combatant.kind === 'player' ? 'Player character' : 'Custom combatant'}
                      </small>
                    </div>
                    <Form.Control
                      className="encounter-initiative-input"
                      type="number"
                      aria-label={`${combatant.characterName} initiative`}
                      placeholder="Init."
                      value={combatant.initiative}
                      disabled={encounterStarted}
                      onChange={(event) => setEncounterInitiative(combatant.id, event.target.value)}
                    />
                    {combatant.kind === 'npc' && !encounterStarted ? (
                      <Button
                        size="sm"
                        variant="outline-secondary"
                        onClick={() => rollNpcInitiative(combatant.id)}
                      >
                        Roll
                      </Button>
                    ) : null}
                    {!encounterStarted ? (
                      <Button
                        size="sm"
                        variant="link"
                        className="encounter-remove"
                        aria-label={`Remove ${combatant.characterName}`}
                        onClick={() => removeEncounterCombatant(combatant.id)}
                      >
                        Remove
                      </Button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}

            {!encounterStarted ? (
              <div className="encounter-custom-entry">
                <Form.Control
                  type="text"
                  aria-label="Custom combatant name"
                  placeholder="Add another combatant"
                  value={newEntry.characterName}
                  onChange={(event) => handleNewEntryChange('characterName', event.target.value)}
                />
                <Form.Control
                  type="number"
                  aria-label="Custom combatant initiative"
                  placeholder="Init."
                  value={newEntry.initiative}
                  onChange={(event) => handleNewEntryChange('initiative', event.target.value)}
                />
                <Button variant="outline-primary" onClick={handleNewEntrySubmit}>Add</Button>
              </div>
            ) : null}
          </section>
        </div>
      </div>
    );
  };

  const renderWorkspaceBody = () => {
    switch (currentContent) {
      case 'home':
        return renderHomeDashboard();
      case 'lootBoxes':
        return renderLootBoxes();
      case 'playerInventories':
        return renderPlayerInventories();
      case 'initiative':
        return renderInitiative();
      case 'npcCards':
        return renderNpcCards();
      case 'randomTables':
      case 'Random Tables':
        return renderRandomTables();
      case 'transactionHistory':
      case 'Transaction History':
        return renderTransactionHistory();
      case 'encounterBuilder':
        return renderEncounterBuilder();
      case 'soundPlayer':
        return <DMSoundPlayerWorkspace />;
      case 'campaignSettings':
        return <CampaignSettings headers={headers} campaignID={headers?.campaignID || headers?.CampaignID} embedded />;
      default:
        return renderHomeDashboard();
    }
  };

  const workspaceTitle = activeTool?.label || 'DM Tools Home';
  const workspaceDescription =
    activeTool?.description ||
    'Choose a tool from the rail to open its workspace, or start from one of the quick actions below.';
  const workspaceActionLabel = activeTool?.actionLabel || null;
  const workspaceAction = activeTool?.action || null;


  // TODO: Future Expansion
  const handleShowBuildEncounter = () => {
    fetchPlayers();
    fetchNpcs(headers?.CampaignID || headers?.campaignID);
    setCurrentContent('encounterBuilder');
  };

  return (
    <>
      <div className="dmtools-page">
        <aside className="dmtools-rail">
          <div className="dmtools-rail-header">
            <h1>DM Tools</h1>
            <p>GM workbench</p>
          </div>

          <div className="dmtools-rail-nav">
            <button
              type="button"
              className={`dmtools-rail-home ${currentContent === 'home' ? 'is-active' : ''}`}
              onClick={() => setCurrentContent('home')}
            >
              <span>Home</span>
              <ChevronRightIcon fontSize="small" />
            </button>

            {TOOL_GROUPS.map((group) => (
              <div className="dmtools-rail-group" key={group.title}>
                <div className="dmtools-rail-group-title">{group.title}</div>

                {group.items.map((tool) => {
                  const isActive =
                    currentContent === tool.id ||
                    (tool.id === 'randomTables' && currentContent === 'Random Tables') ||
                    (tool.id === 'transactionHistory' && currentContent === 'Transaction History');

                  return (
                    <button
                      key={tool.id}
                      type="button"
                      className={`dmtools-rail-item ${isActive ? 'is-active' : ''}`}
                      onClick={() => selectTool(tool.id)}
                    >
                      <span className="dmtools-rail-item-icon">{tool.icon}</span>
                      <span className="dmtools-rail-item-text">
                        <span className="dmtools-rail-item-label">{tool.label}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </aside>

        <section className="dmtools-workspace">
          <div className="dmtools-workspace-header">
            <div className="dmtools-workspace-heading">
              <h2>{workspaceTitle}</h2>
              <p>{workspaceDescription}</p>
            </div>

            {workspaceActionLabel && workspaceAction ? (
              <div className="dmtools-workspace-actions">
                <Button onClick={workspaceAction}>{workspaceActionLabel}</Button>
              </div>
            ) : null}
          </div>

          <div className="dmtools-workspace-body">
            {renderWorkspaceBody()}
          </div>
        </section>
      </div>

      {/* Create Loot Box Modal */}
      <Modal show={lootBoxModalOpen} onHide={() => setLootBoxModalOpen(false)} centered fullscreen>
        <Modal.Header closeButton>
          <Modal.Title>{editingLootBoxId === null ? 'Create Loot Box' : 'Edit Loot Box'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Row>
            <Col>
              <InputGroup className="mb-3">
                <FormControl
                  placeholder="Search for items"
                  value={searchText}
                  onChange={handleItemSearchChange}
                />
              </InputGroup>
              <Table striped bordered hover>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Add</th>
                  </tr>
                </thead>
                <tbody>
                  {items.filter(item => item.name.toLowerCase().includes(searchText.toLowerCase())).map((item, i) => (
                    <tr key={i}>
                      <td>{item.name}</td>
                      <td>
                        <Button variant="primary" onClick={() => handleItemClick(item)}>Add</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Col>
            <Col>
              <label>Loot Box Name:
                <input
                  type="text"
                  placeholder="Loot Box Name"
                  value={lootBoxName}
                  onChange={e => setLootBoxName(e.target.value)}
                />
              </label>
              <Form.Group className="mt-3">
                <Form.Label>Catalog scope</Form.Label>
                <Form.Select value={lootBoxModuleKey} onChange={event=>setLootBoxModuleKey(event.target.value)}>
                  <option value="">Entire campaign</option>
                  {catalogModules.map(module=><option key={module.module_key} value={module.module_key}>{module.module_name}</option>)}
                </Form.Select>
                <Form.Text>Optionally associate this loot box with an installed module.</Form.Text>
              </Form.Group>
              <Table striped bordered hover>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Quantity</th>
                    <th>Remove</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedItems.map((item, i) => (
                    <tr key={i}>
                      <td>{item.name}</td>
                      <td>
                        <Form.Control
                          type="number"
                          placeholder="Quantity"
                          value={item.quantity}
                          onChange={e => handleItemQuantityChange(item.id, e.target.value)}
                        />
                      </td>
                      <td>
                        <Button variant="danger" onClick={() => handleItemRemoveClick(item)}>Remove</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Col>
          </Row>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={handleSaveLootBox}>Save</Button>
        </Modal.Footer>
      </Modal>

      {/* View Loot Box Modal */}
      <Modal show={viewLootBoxModal} onHide={() => setViewLootBoxModal(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>
            <Row>
              <Col>
                {selectedLootBox?.name}
              </Col>
              {selectedLootBox?.editable!==false&&<Col>
                <Button variant="primary" onClick={editLootBox}>
                  <EditIcon /> Edit
                </Button>
                <Button variant="danger" onClick={() => deleteLootBox(selectedLootBox)}>
                  <DeleteIcon /> Delete
                </Button>
              </Col>}
            </Row>
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Table striped bordered hover>
            <thead>
              <tr>
                <th>Name</th>
                <th>Quantity</th>
              </tr>
            </thead>
            <tbody>
              {selectedLootBox?.items.map((item, i) => (
                <tr key={i}>
                  <td>{item.name}</td>
                  <td>{item.quantity}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Modal.Body>
        <Modal.Footer>
          <Form.Control as="select" value={selectedPlayer ? JSON.stringify(selectedPlayer) : ''} onChange={e => setSelectedPlayer(JSON.parse(e.target.value))}>
            <option value="" disabled>Select a player</option>
            {players.map((player, index) => (
              <option key={index} value={JSON.stringify(player)}>{player.character_name}</option>
            ))}
          </Form.Control>
          <Button variant="primary" onClick={() => issueLootToPlayer(selectedLootBox)}>
            Issue to Player
          </Button>
        </Modal.Footer>
      </Modal>

      {/* View Player Inventory Modal */}
      <Modal show={viewPlayerInventoryModal} onHide={() => setViewPlayerInventoryModal(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>
            <Row>
              {selectedPlayer?.character_name}
            </Row>
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Table striped bordered hover>
            <thead>
              <tr>
                <th>Item</th>
                <th>Quantity</th>
              </tr>
            </thead>
            <tbody>
              {inventory?.map((item, i) => (
                <tr key={i}>
                  <td>{item.name}</td>
                  <td>{item.quantity}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Modal.Body>
      </Modal>

      {/* Create NPC Modal */}
      <Modal show={npcModalOpen} onHide={() => setNpcModalOpen(false)} centered backdrop="static">
        <Modal.Header closeButton>
          <Modal.Title>Create NPC</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form>
            <InputFormGroup label="Name" type="text" value={npcData.name} onChange={handleInputChange} name="name" />
            <Form.Group>
              <Form.Label>Size</Form.Label>
              <Form.Control as="select" value={npcData.size} onChange={handleInputChange} name="size">
                <option value="Tiny">Tiny</option>
                <option value="Small">Small</option>
                <option value="Medium">Medium</option>
                <option value="Large">Large</option>
                <option value="Huge">Huge</option>
                <option value="Gargantuan">Gargantuan</option>
              </Form.Control>
            </Form.Group>
            <InputFormGroup label="Creature Type" type="text" value={npcData.creatureType} onChange={handleInputChange} name="creatureType" />
            <InputFormGroup label="Creature Subtype" type="text" value={npcData.creatureSubtype} onChange={handleInputChange} name="creatureSubtype" />
            <Form.Group>
              <Form.Label>Alignment</Form.Label>
              <Form.Control as="select" value={npcData.alignment} onChange={handleInputChange} name="alignment">
                <option value="" disabled>Select alignment</option>
                {alignments.map(alignment => (
                  <option key={alignment} value={alignment}>{alignment}</option>
                ))}
              </Form.Control>
            </Form.Group>
            <InputFormGroup label="AC" type="number" value={npcData.ac} onChange={handleInputChange} name="ac" />
            <InputFormGroup label="HP" type="number" value={npcData.hp} onChange={handleInputChange} name="hp" />
            <InputFormGroup label="Speed" type="number" value={npcData.speed} onChange={handleInputChange} name="speed" />
            <InputFormGroup label="Strength" type="number" value={npcData.strength} onChange={handleInputChange} name="strength" />
            <InputFormGroup label="Dexterity" type="number" value={npcData.dexterity} onChange={handleInputChange} name="dexterity" />
            <InputFormGroup label="Constitution" type="number" value={npcData.constitution} onChange={handleInputChange} name="constitution" />
            <InputFormGroup label="Intelligence" type="number" value={npcData.intelligence} onChange={handleInputChange} name="intelligence" />
            <InputFormGroup label="Wisdom" type="number" value={npcData.wisdom} onChange={handleInputChange} name="wisdom" />
            <InputFormGroup label="Charisma" type="number" value={npcData.charisma} onChange={handleInputChange} name="charisma" />
            <InputFormGroup label="Saving Throws" type="text" value={npcData.saving_throws} onChange={handleInputChange} name="saving_throws" />
            <InputFormGroup label="Skills" type="text" value={npcData.skills} onChange={handleInputChange} name="skills" />
            <InputFormGroup label="Immunities" type="text" value={npcData.immunities} onChange={handleInputChange} name="immunities" />
            <InputFormGroup label="Resistance" type="text" value={npcData.resistance} onChange={handleInputChange} name="resistance" />
            <InputFormGroup label="Senses" type="text" value={npcData.senses} onChange={handleInputChange} name="senses" />
            <InputFormGroup label="Languages" type="text" value={npcData.languages} onChange={handleInputChange} name="languages" />
            <InputFormGroup label="Challenge" type="text" value={npcData.challenge} onChange={handleInputChange} name="challenge" />
            <InputFormGroup label="Traits" type="textarea" value={npcData.traits} onChange={handleInputChange} name="traits" />
            <InputFormGroup label="Actions" type="textarea" value={npcData.actions} onChange={handleInputChange} name="actions" />
            <InputFormGroup label="Description" type="textarea" value={npcData.description} onChange={handleInputChange} name="description" />
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={handleSaveNpc}>Save</Button>
        </Modal.Footer>
      </Modal>

      {/* View NPC Actions Modal */}
      {selectedNpc && (
        <Modal show={true} onHide={() => setSelectedNpc(null)} centered>
          <Modal.Header closeButton>
            <Modal.Title>{selectedNpc.name}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <p><strong>{selectedNpc.size} {selectedNpc.creature_type} ({selectedNpc.creature_subtype}), {selectedNpc.alignment}</strong></p>

            <Row>
              <Col><p><strong>Armor Class:</strong> {selectedNpc.ac}</p></Col>
              <Col><p><strong>Hit Points:</strong> {selectedNpc.hp}</p></Col>
              <Col><p><strong>Speed:</strong> {selectedNpc.speed} ft.</p></Col>
            </Row>

            <p><strong>STR</strong> {selectedNpc.strength}, <strong>DEX</strong> {selectedNpc.dexterity}, <strong>CON</strong> {selectedNpc.constitution},
              <strong>INT</strong> {selectedNpc.intelligence}, <strong>WIS</strong> {selectedNpc.wisdom}, <strong>CHA</strong> {selectedNpc.charisma}</p>

            <hr />

            <Row>
              {selectedNpc.saving_throws ? <Col><p><strong>Saving Throws:</strong> {selectedNpc.saving_throws}</p></Col> : <></>}
              <Col><p><strong>Skills:</strong> {selectedNpc.skills}</p></Col>
              {selectedNpc.immunities ? <Col><p><strong>Immunities:</strong> {selectedNpc.immunities}</p></Col> : <></>}
              {selectedNpc.resistance ? <Col><p><strong>Resistance:</strong> {selectedNpc.resistance}</p></Col> : <></>}
              <Col><p><strong>Senses:</strong> {selectedNpc.senses}</p></Col>
              <Col><p><strong>Languages:</strong> {selectedNpc.languages}</p></Col>
              <Col><p><strong>Challenge:</strong> {selectedNpc.challenge}</p></Col>
            </Row>

            <hr />

            <p><strong><u>Traits</u></strong></p>
            <p>{selectedNpc.traits}</p>

            <p><strong><u>Actions</u></strong></p>
            <p>{selectedNpc.actions}</p>

            <hr />

            <p><strong>Description:</strong> {selectedNpc.description}</p>
          </Modal.Body>
        </Modal>
      )}

      {/* Modal for creating/editing a random table */}
      <Modal show={randomTableModalOpen} onHide={() => setRandomTableModalOpen(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>{isEditing ? 'Edit Random Table' : 'Create Random Table'}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form>
            <InputFormGroup
              label="Table Name"
              type="text"
              placeholder="Table Name"
              value={randomTableData.name}
              onChange={(e) => setRandomTableData(prevData => ({ ...prevData, name: e.target.value }))}
            />
            <InputFormGroup
              label="Description"
              type="textarea"
              placeholder="Description"
              value={randomTableData.description}
              onChange={(e) => setRandomTableData(prevData => ({ ...prevData, description: e.target.value }))}
            />
            <InputFormGroup
              label="Dice Type"
              type="text"
              placeholder="Dice Type (e.g., 1d100)"
              value={randomTableData.diceType}
              onChange={(e) => setRandomTableData(prevData => ({ ...prevData, diceType: e.target.value }))}
            />
            <Form.Group className="mt-3">
              <Form.Label>Catalog scope</Form.Label>
              <Form.Select value={randomTableData.moduleKey||''} onChange={event=>setRandomTableData(value=>({...value,moduleKey:event.target.value}))}>
                <option value="">Entire campaign</option>
                {catalogModules.map(module=><option key={module.module_key} value={module.module_key}>{module.module_name}</option>)}
              </Form.Select>
              <Form.Text>Optionally associate this roll table with an installed module.</Form.Text>
            </Form.Group>

            <hr />
            <h5>Entries</h5>

            <Row>
              <Col>
                <Form.Control
                  type="number"
                  placeholder="Min Roll"
                  value={entryMinRoll}
                  onChange={(e) => setEntryMinRoll(e.target.value)}
                />
              </Col>
              <Col>
                <Form.Control
                  type="number"
                  placeholder="Max Roll"
                  value={entryMaxRoll}
                  onChange={(e) => setEntryMaxRoll(e.target.value)}
                />
              </Col>
              <Col>
                <Form.Control
                  type="text"
                  placeholder="Result"
                  value={entryResult}
                  onChange={(e) => setEntryResult(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddEntry();
                    }
                  }}
                />
              </Col>
              <Col>
                <Button variant="primary" onClick={handleAddEntry}>Add Entry</Button>
              </Col>
            </Row>

            <Table striped bordered hover className="mt-3">
              <thead>
                <tr>
                  <th>Min Roll</th>
                  <th>Max Roll</th>
                  <th>Result</th>
                  <th>Remove</th>
                </tr>
              </thead>
              <tbody>
                {randomTableData.entries
                  .sort((a, b) => a.min_roll - b.min_roll)
                  .map((entry, index) => (
                    <tr key={index}>
                      <td>{entry.min_roll}</td>
                      <td>{entry.max_roll}</td>
                      <td>{entry.result}</td>
                      <td>
                        <Button variant="danger" onClick={() => handleRemoveEntry(index)}>Remove</Button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </Table>
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setRandomTableModalOpen(false)}>Close</Button>
          <Button variant="primary" onClick={handleSaveRandomTable}>{isEditing ? 'Save Changes' : 'Save Table'}</Button>
        </Modal.Footer>
      </Modal>

      {/* View Random Table Modal */}
      <Modal show={viewTableModalOpen} onHide={() => setViewTableModalOpen(false)} centered>
        <Modal.Header closeButton>
          <Modal.Title>
            <Row>
              <Col>
                {selectedTable?.name}
              </Col>
              {selectedTable?.editable!==false&&<Col>
                <Button variant="primary" onClick={editRandomTable}>
                  <EditIcon />
                </Button>
                <Col>
                  <Button variant="danger" onClick={() => deleteRandomTable(selectedTable.id)}>
                    <DeleteIcon />
                  </Button>
                </Col>
              </Col>}
            </Row>
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p>{selectedTable?.description}</p>
          <p>Dice Type: {selectedTable?.dice_type}</p>
          <Table striped bordered hover>
            <thead>
              <tr>
                <th>Min Roll</th>
                <th>Max Roll</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {selectedTable?.table_entries
                .sort((a, b) => a.min_roll - b.min_roll)
                .map((entry, index) => (
                  <tr key={index}>
                    <td>{entry.min_roll}</td>
                    <td>{entry.max_roll}</td>
                    <td>{entry.result}</td>
                  </tr>
                ))}
            </tbody>
          </Table>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setViewTableModalOpen(false)}>Close</Button>
        </Modal.Footer>
      </Modal>
    </>
  );
}

export default DMTools;
