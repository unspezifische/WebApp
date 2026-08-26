import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { Card, Button, Modal, Navbar, Container, Row, Col, Form, Carousel, Accordion } from 'react-bootstrap';
import campaignIcon from './campaign.webp';

import CreateCharacterModal from './CreateCharacterModal';

const campaignSystemLabel = (campaign) => (
  campaign.system === 'D&D' && campaign.ruleset
    ? `D&D · ${campaign.ruleset}`
    : campaign.system
);

const AccountProfile = ({ headers, setAccountType, setSelectedCampaign, setCharacterName, dmLandingPath = '/dmTools', primaryOrigin = window.location.origin }) => {
  const navigate = useNavigate();

  const [campaigns, setCampaigns] = useState([]);
  const [characters, setCharacters] = useState([]);
  const [unaffiliatedCharacters, setUnaffiliatedCharacters] = useState([]);

  const [showModalCampaign, setShowModalCampaign] = useState(false);
  const [showModalCharacter, setShowModalCharacter] = useState(false);
  const [showModalSelectCharacter, setShowModalSelectCharacter] = useState(false);

  const handleCloseModalCampaign = () => setShowModalCampaign(false);
  const handleCreateCampaign = () => setShowModalCampaign(true);

  const handleCloseModalCharacter = () => setShowModalCharacter(false);
  const handleCreateCharacter = () => setShowModalCharacter(true);

  const handleCloseModalSelectCharacter = () => setShowModalSelectCharacter(false);

  // Get camapigns and characters
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [campaignsResponse, charactersResponse] = await Promise.all([
          axios.get('/api/campaigns', { headers }),
          axios.get('/api/characters', { headers })
        ]);

        setCampaigns(campaignsResponse.data);
        setCharacters(charactersResponse.data);

        console.log("AccountProfile- api/characters:", charactersResponse.data);
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };

    fetchData();
  }, [headers]);

  // Accepts a character object and sets the character name and ID
  const handleSelectCharacter = (character) => {
    if (character) {
      console.log("AccountProfile- selected character:", character);
      setAccountType('Player');
      console.log("AccountProfile- selected character name:", character.name);
      // Set the character name for downstream pages (Chat/Inventory/Journal)
      setCharacterName(character.name || character.Name || character.character_name || '');

      // Set the selected campaign with the required format
      setSelectedCampaign({
        id: character.campaignID,
        name: character.campaign,
        dmId: null,
        ownerId: null,
        rulesSystem: character.system,
      });
      console.log("AccountProfile- selected campaign:", character.campaign, character.campaignID);
  
      navigate('/characterSheet');
    } else {
      console.log("Profile- no character selected");
    }
  };

  const handleCampaignSelection = (campaign) => {
    console.log("header- AccountProfile", headers);
    // Add the Campaign-ID to the headers
    headers['Campaign-ID'] = campaign.id || 1;
    setSelectedCampaign({
      id: campaign.id,
      name: campaign.name,
      dmId: campaign.dm_id,
      ownerId: campaign.owner_id,
      ruleset: campaign.ruleset,
      rulesSystem: campaign.rules_system,
    });
    if (campaign.dm_id === headers.userID) {
      axios.get('/api/characters', { headers })
        .then(response => {
          console.log("AccountProfile- api/characters:", response.data);
        })
      setAccountType('DM');
      setCharacterName('DM');
      navigate(dmLandingPath);
    } 
    else if (campaign.owner_id === headers.userID) {
      axios.get('/api/characters', { headers })
        .then(response => {
          console.log("AccountProfile- api/characters:", response.data);
        })
      setAccountType('DM');
      setCharacterName('Admin');
      navigate(dmLandingPath);
    } else {
      setAccountType('Player');
      axios.get('/api/characters', { headers })
        .then(response => {
          // console.log("AccountProfile- api/characters:", response.data);
          // Filter the user's characters for those that are affiliated with the selected campaign
          const affiliatedCharacters = response.data.filter(character => character.campaignID === campaign.id);
          console.log("affiliatedCharacters:", affiliatedCharacters);
          if (affiliatedCharacters.length > 0) {
            console.log("Selected Character-", affiliatedCharacters[0]);
            console.log("Selected Character ID-", affiliatedCharacters[0].id);
            console.log("Selected Character Name-", affiliatedCharacters[0].name || affiliatedCharacters[0].Name || affiliatedCharacters[0].character_name);
            setCharacterName(affiliatedCharacters[0].name || affiliatedCharacters[0].Name || affiliatedCharacters[0].character_name || '');
            // setCharacterID(affiliatedCharacters[0].id);
            navigate('/characterSheet');
          } else {
            // Memberships may exist before the player has made a character.
            // Keep any reusable characters available for a later association
            // workflow, but open character creation now instead of crashing on
            // an attempted assignment to the React state setter.
            setUnaffiliatedCharacters(response.data.filter(character => !character.campaignID && character.system === (campaign.rules_system || campaign.system)));
            handleCreateCharacter();
          }
        })
        .catch(error => {
          console.error('Error fetching profile:', error);
        });
    }

  };

  const handleWikiSelection = (campaign) => {
    console.log("header- AccountProfile", headers);
    // Add the Campaign-ID to the headers
    headers['Campaign-ID'] = campaign.id || 1;
    setSelectedCampaign({
      id: campaign.id,
      name: campaign.name,
      dmId: campaign.dm_id,
      ownerId: campaign.owner_id,
      ruleset: campaign.ruleset,
      rulesSystem: campaign.rules_system,
    });

    console.log("opening wiki for", campaign.name);

    if (campaign.dm_id === headers.userID) {
      axios.get('/api/characters', { headers })
        .then(response => {
          console.log("AccountProfile- api/characters:", response.data);
        })
      setAccountType('DM');
      setCharacterName('DM');
      navigate(dmLandingPath);
    }
    else if (campaign.owner_id === headers.userID) {
      axios.get('/api/characters', { headers })
        .then(response => {
          console.log("AccountProfile- api/characters:", response.data);
        })
      setAccountType('DM');
      setCharacterName('Admin');
      navigate(dmLandingPath);
    } else {
      setAccountType('Player');
      axios.get('/api/characters', { headers })
        .then(response => {
          // console.log("AccountProfile- api/characters:", response.data);
          // Filter the user's characters for those that are affiliated with the selected campaign
          const affiliatedCharacters = response.data.filter(character => character.campaignID === campaign.id);
          console.log("affiliatedCharacters:", affiliatedCharacters);
          if (affiliatedCharacters.length > 0) {
            console.log("Selected Character-", affiliatedCharacters[0]);
            console.log("Selected Character ID-", affiliatedCharacters[0].id);
            console.log("Selected Character Name-", affiliatedCharacters[0].name);
            setCharacterName(affiliatedCharacters[0].name);
            navigate('/characterSheet');
          } else {
            setUnaffiliatedCharacters(response.data.filter(character => !character.campaignID && character.system === (campaign.rules_system || campaign.system)));
            handleCreateCharacter();
          }
        })
        .catch(error => {
          console.error('Error fetching profile:', error);
        });
    }

    // Store headers in local storage
    localStorage.setItem('userID', headers['userID']);
    localStorage.setItem('characterName', headers['characterName']);
    console.log("Stored header in local storage");

    // Construct the destination URL without encoding
    var destinationURL = primaryOrigin + '/' + encodeURIComponent(campaign.name) + "/Main Page";
    var destinationPage = encodeURIComponent(campaign.name) + "/Main Page";
    console.log("Destination URL: " + destinationURL);
    console.log("Destination Page: " + destinationPage);

    // Encode the entire destination URL
    var encodedDestination = encodeURIComponent(destinationPage);
    console.log("Encoded URL: " + encodedDestination);

    // Include the encoded destination URL as a query parameter in the login URL
    var loginUrl = primaryOrigin + '/login?redirect=/wiki/' + encodedDestination;
    console.log("URL with Redirect: " + loginUrl);

    // Open the login URL in a new window
    window.open(loginUrl, '_blank');
  };

  const [newCampaign, setNewCampaign] = useState({
    name: '',
    system: 'D&D',
    ruleset: '5e',
    module: '',
    description: '',
    calendar_enabled: true,
    calendar_format: 'harptos',
    calendar_year: 1,
    calendar_month: 1,
    calendar_day: 1,
  });

  const [newCharacter, setNewCharacter] = useState({
    name: '',
    system: 'D&D',
    class: ''
  });

  const handleInputChange = (event) => {
    setNewCampaign({
      ...newCampaign,
      [event.target.name]: event.target.type === 'checkbox' ? event.target.checked : event.target.value
    });
  };

  const handleFormSubmit = (event) => {
    event.preventDefault();
    axios.post('/api/campaigns', newCampaign, { headers })
      .then(response => {
        setCampaigns([...campaigns, response.data]);
        handleCloseModalCampaign();
      })
      .catch(error => {
        console.error('Error creating campaign:', error);
      });
  };

  // For the Carousel: className='d-flex flex-column align-items-center'
  return (
    <>
      <Container fluid>
        <Row>
          <h1>Account Profile</h1>
        </Row>
        {/* Carousel */}
        <Row >
          <Carousel>
            {campaigns.map((campaign, index) => (
              <Carousel.Item key={campaign.id}>
                <Carousel.Caption>
                  <h3 style={{ mixBlendMode: 'difference', color: 'red' }}>{campaign.name}</h3>
                  <p style={{ mixBlendMode: 'difference', color: 'red' }}>{campaignSystemLabel(campaign)}</p>
                </Carousel.Caption>
                <img
                  className="d-flex justify-content-center align-items-center"
                  style={{height: '40vh', margin: '0 auto' }}
                  src={campaign.icon || campaignIcon}
                  alt={`Campaign ${index}`}
                />
              </Carousel.Item>
            ))}
            {characters.map((character, index) => (
              <Carousel.Item key={character.id}>
                <Carousel.Caption>
                  <h3 style={{ mixBlendMode: 'difference', color: 'red' }}>{character.name}</h3>
                  <p style={{ mixBlendMode: 'difference', color: 'red' }}>{character.Class}</p>
                  <p style={{ mixBlendMode: 'difference', color: 'red' }}>{character.campaign}</p>
                </Carousel.Caption>
                <img
                  className="d-flex justify-content-center align-items-center"
                  style={{height: '40vh', margin: '0 auto' }}
                  src={process.env.PUBLIC_URL + '/avatars/' + character.icon || campaignIcon}
                  alt={`Character ${index}`}
                />
              </Carousel.Item>
            ))}
          </Carousel>
        </Row>

        {/* Campaigns, Characters, and Wikis */}
        <Row>
          <Accordion defaultActiveKey="0">
            {/* Campaigns */}
            <Accordion.Item eventKey="0">
              <Accordion.Header>
                <h3>My Campaigns</h3>
              </Accordion.Header>
              <Accordion.Body>
                {campaigns.map((campaign) => (
                  <Col sm={4} key={campaign.id}>
                    <Card
                      role="button"
                      tabIndex={0}
                      aria-label={`Open campaign ${campaign.name}`}
                      style={{ width: '18rem', height: '90px', marginBottom: '1rem' }}
                      onClick={() => handleCampaignSelection(campaign)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') handleCampaignSelection(campaign);
                      }}
                    >
                      <Row>
                        <Col xs={4}>
                          <Card.Img variant="top" src={campaign.icon || campaignIcon} />
                        </Col>
                        <Col xs={8}>
                          <Card.Body>
                            <Card.Title>{campaign.name}</Card.Title>
                            <Card.Subtitle className="mb-2 text-muted">{campaignSystemLabel(campaign)}</Card.Subtitle>
                            {/* Add more details here */}
                          </Card.Body>
                        </Col>
                      </Row>
                    </Card>
                  </Col>
                ))}
                <Col sm={4}>
                  <Card style={{ width: '18rem', height: '90px', marginBottom: '1rem' }} onClick={handleCreateCampaign}>
                    <Row>
                      <Col xs={4}>
                        <Card.Img variant="top" src={campaignIcon} />
                      </Col>
                      <Col xs={8}>
                        <Card.Body>
                          <Card.Title>Create A New Campaign</Card.Title>
                        </Card.Body>
                      </Col>
                    </Row>
                  </Card>
                </Col>
              </Accordion.Body>
            </Accordion.Item>
            {/* Characters */}
            <Accordion.Item eventKey="1">
              <Accordion.Header>
                <h3>My Characters</h3>
              </Accordion.Header>
              <Accordion.Body>
                {characters.map((character) => (
                  <Card
                    key={character.id}
                    style={{ width: '18rem', height: '90px', marginBottom: '1rem' }}
                    onClick={() => handleSelectCharacter(character)}
                  >
                    <Row>
                      <Col xs={4}>
                        <Card.Img variant="top" src={character.icon} />
                      </Col>
                      <Col xs={8}>
                        <Card.Body>
                          <Card.Title>{character.Name}</Card.Title>
                          <Card.Subtitle className="mb-2 text-muted">{character.Class}</Card.Subtitle>
                        </Card.Body>
                      </Col>
                    </Row>
                  </Card>
                ))}
                <Col sm={4}>
                  <Card style={{ width: '18rem', height: '90px', marginBottom: '1rem' }} onClick={handleCreateCharacter}>
                    <Row>
                      <Col xs={4}>
                        <Card.Img fluid src={campaignIcon} />
                      </Col>
                      <Col xs={8}>
                        <Card.Body>
                          <Card.Title>Create A New Character</Card.Title>
                        </Card.Body>
                      </Col>
                    </Row>
                  </Card>
                </Col>
              </Accordion.Body>
            </Accordion.Item>
            {/* Wikis */}
            <Accordion.Item eventKey="2">
              <Accordion.Header>
                <h3>Campaign Wikis</h3>
              </Accordion.Header>
              <Accordion.Body>
                {campaigns.map((campaign) => (
                  <Col sm={4} key={campaign.id}>
                    <Card style={{ width: '18rem', height: '90px', marginBottom: '1rem' }} onClick={() => handleWikiSelection(campaign)}>
                      <Row>
                        <Col xs={4}>
                          <Card.Img variant="top" src={campaign.icon || campaignIcon} />
                        </Col>
                        <Col xs={8}>
                          <Card.Body>
                            <Card.Title>{campaign.name}</Card.Title>
                            <Card.Subtitle className="mb-2 text-muted">{campaignSystemLabel(campaign)}</Card.Subtitle>
                            {/* Add more details here */}
                          </Card.Body>
                        </Col>
                      </Row>
                    </Card>
                  </Col>
                ))}
                <Col sm={4}>
                  <Card style={{ width: '18rem', height: '90px', marginBottom: '1rem' }} onClick={handleCreateCampaign}>
                    <Row>
                      <Col xs={4}>
                        <Card.Img variant="top" src={campaignIcon} />
                      </Col>
                      <Col xs={8}>
                        <Card.Body>
                          <Card.Title>Create A New Campaign</Card.Title>
                        </Card.Body>
                      </Col>
                    </Row>
                  </Card>
                </Col>
              </Accordion.Body>
            </Accordion.Item>
          </Accordion>
        </Row>
      </Container>

      {/* Select Character Modal */}
      <Modal show={showModalSelectCharacter} onHide={handleCloseModalSelectCharacter}>
        <Modal.Header closeButton>
          <Modal.Title>Select Character</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form>
            <Form.Group controlId="characterSelect">
              <Form.Label>Character</Form.Label>
              <Form.Control as="select" name="character" onChange={handleInputChange} required>
                <option value="">Select a character</option>
                {unaffiliatedCharacters.map((character) => (
                  <option key={character.id} value={character.id}>{character.name}</option>
                ))}
              </Form.Control>
            </Form.Group>
            <Button variant="primary" type="submit">Select Character</Button>
          </Form>
        </Modal.Body>
      </Modal>

      {/* Campaign Creation Modal */}
      <Modal show={showModalCampaign} onHide={handleCloseModalCampaign}>
        <Modal.Header closeButton>
          <Modal.Title>Create New Campaign</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={handleFormSubmit}>
            <Form.Group controlId="campaignName">
              <Form.Label>Campaign Name</Form.Label>
              <Form.Control type="text" name="name" value={newCampaign.name} onChange={handleInputChange} required />
            </Form.Group>
            <Form.Group controlId="campaignSystem">
              <Form.Label>System</Form.Label>
              <Form.Control as="select" name="system" value={newCampaign.system} onChange={handleInputChange} required>
                <option>D&D</option>
                {/* Add more options here as needed */}
              </Form.Control>
            </Form.Group>
            {newCampaign.system === 'D&D' && <Form.Group controlId="campaignRuleset" className="mt-3">
              <Form.Label>D&amp;D Ruleset</Form.Label>
              <Form.Control as="select" name="ruleset" value={newCampaign.ruleset} onChange={handleInputChange} required>
                <option value="3.5e">3.5e</option>
                <option value="4e">4e</option>
                <option value="5e">5e</option>
                <option value="5e (2024)">5e (2024)</option>
              </Form.Control>
            </Form.Group>}
            <Form.Group controlId="campaignModule">
              <Form.Label>Module</Form.Label>
              <Form.Control as="select" name="module" value={newCampaign.module} onChange={handleInputChange} >
                <option value="">Select a module (optional)</option>
                <option>Lost Mine of Phandelver</option>
                <option>Waterdeep Dragon Heist</option>
                {/* TODO- Add more options here as needed. And probably populate this based on "Module" in the "game_element" table of the database */}
                {/* TODO TODO- create JSON files for modules */}
              </Form.Control>
            </Form.Group>
            <Form.Group controlId="campaignDescription">
              <Form.Label>Description</Form.Label>
              <Form.Control as="textarea" name="description" value={newCampaign.description} onChange={handleInputChange} />
            </Form.Group>
            <fieldset className="mt-3 border rounded p-3">
              <legend className="fs-6 mb-2">Campaign Calendar</legend>
              {newCampaign.module ? (
                <Form.Text className="d-block mb-2">
                  This module includes a calendar. Its calendar and starting year will be configured with the campaign.
                </Form.Text>
              ) : (
                <>
                  <Form.Check
                    className="mb-3"
                    type="switch"
                    id="campaignCalendarEnabled"
                    name="calendar_enabled"
                    label="Set up a calendar now"
                    checked={newCampaign.calendar_enabled}
                    onChange={handleInputChange}
                  />
                  {newCampaign.calendar_enabled && (
                    <>
                      <Form.Group controlId="campaignCalendarFormat" className="mb-2">
                        <Form.Label>Calendar System</Form.Label>
                        <Form.Select name="calendar_format" value={newCampaign.calendar_format} onChange={handleInputChange}>
                          <option value="harptos">Calendar of Harptos</option>
                          <option value="gregorian">Gregorian Calendar</option>
                        </Form.Select>
                      </Form.Group>
                      <Row>
                        <Col sm={6}>
                          <Form.Group controlId="campaignCalendarYear">
                            <Form.Label>Starting Year</Form.Label>
                            <Form.Control type="number" name="calendar_year" value={newCampaign.calendar_year} onChange={handleInputChange} required />
                          </Form.Group>
                        </Col>
                        <Col sm={3}>
                          <Form.Group controlId="campaignCalendarMonth">
                            <Form.Label>Month</Form.Label>
                            <Form.Control type="number" min="1" max="12" name="calendar_month" value={newCampaign.calendar_month} onChange={handleInputChange} required />
                          </Form.Group>
                        </Col>
                        <Col sm={3}>
                          <Form.Group controlId="campaignCalendarDay">
                            <Form.Label>Day</Form.Label>
                            <Form.Control type="number" min="1" max="31" name="calendar_day" value={newCampaign.calendar_day} onChange={handleInputChange} required />
                          </Form.Group>
                        </Col>
                      </Row>
                    </>
                  )}
                </>
              )}
            </fieldset>
            <Button variant="primary" type="submit">Create Campaign</Button>
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={handleCloseModalCampaign}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Character Creation Modal */}
      <CreateCharacterModal show={showModalCharacter} setShow={setShowModalCharacter} onHide={handleCloseModalCharacter} headers={headers} />
    </>
  );
};

export default AccountProfile;
