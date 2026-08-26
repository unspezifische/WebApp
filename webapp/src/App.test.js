import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import App from './App';

jest.mock('axios');
jest.mock('socket.io-client', () => () => ({
  on: jest.fn(),
  off: jest.fn(),
  emit: jest.fn(),
  connect: jest.fn(),
  disconnect: jest.fn(),
}));

jest.mock('./Menu', () => () => <div data-testid="campaign-menu">Menu</div>);
jest.mock('./AccountProfile', () => () => <div>Campaign picker</div>);
jest.mock('./DMTools', () => () => <div>DM tools</div>);
jest.mock('./SettlementManager', () => () => <div>Settlement manager</div>);
jest.mock('./SettlementPlayerView', () => () => <div>Settlement player view</div>);
jest.mock('./CharacterSheet', () => () => <div>Character sheet</div>);
jest.mock('./InventoryView', () => () => <div>Inventory</div>);
jest.mock('./Journal', () => () => <div>Journal</div>);
jest.mock('./Library', () => () => <div>Library</div>);
jest.mock('./Calendar', () => () => <div>Calendar</div>);
jest.mock('./Chat', () => () => <div>Chat</div>);
jest.mock('./Register', () => () => <div>Register</div>);

const storedCampaign = {
  id: 7,
  name: 'Waterdeep',
  dmId: 42,
  ownerId: 42,
};

function storeCampaignSession() {
  localStorage.setItem('token', 'stored-token');
  localStorage.setItem('accountType', 'DM');
  localStorage.setItem('selectedCampaign', JSON.stringify(storedCampaign));
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  window.history.replaceState({}, '', '/login');
  axios.get.mockResolvedValue({ data: {} });
});

test('a valid restored session cannot leave the campaign shell blank at /login', async () => {
  storeCampaignSession();
  axios.post.mockResolvedValue({
    data: { success: true, username: 'dm', id: 42 },
  });

  render(<App />);

  expect(await screen.findByText('DM tools')).toBeInTheDocument();
  expect(screen.getByTestId('campaign-menu')).toBeInTheDocument();
  expect(window.location.pathname).toBe('/dmTools');
});

test('the campaign picker never renders inside the campaign sidebar', async () => {
  storeCampaignSession();
  window.history.replaceState({}, '', '/accountProfile');
  axios.post.mockResolvedValue({
    data: { success: true, username: 'dm', id: 42 },
  });

  render(<App />);

  expect(await screen.findByText('Campaign picker')).toBeInTheDocument();
  expect(screen.queryByTestId('campaign-menu')).not.toBeInTheDocument();
});

test('an expired token clears stale campaign state before showing login', async () => {
  storeCampaignSession();
  window.history.replaceState({}, '', '/dmTools');
  axios.post.mockRejectedValue({ response: { status: 401 } });

  render(<App />);

  await waitFor(() => expect(window.location.pathname).toBe('/login'));
  expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
  expect(localStorage.getItem('token')).toBeNull();
  expect(localStorage.getItem('selectedCampaign')).toBeNull();
  expect(localStorage.getItem('accountType')).toBeNull();
  expect(screen.queryByTestId('campaign-menu')).not.toBeInTheDocument();
});

test('a fresh login discards stale campaign metadata and opens the campaign picker', async () => {
  localStorage.setItem('accountType', 'DM');
  localStorage.setItem('selectedCampaign', JSON.stringify(storedCampaign));
  axios.post.mockImplementation((url) => {
    if (url === '/api/login') {
      return Promise.resolve({
        data: { access_token: 'new-token', userID: 42, username: 'dm' },
      });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });

  render(<App />);
  fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'DM' } });
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Login' }));

  expect(await screen.findByText('Campaign picker')).toBeInTheDocument();
  await waitFor(() => expect(window.location.pathname).toBe('/accountProfile'));
  expect(localStorage.getItem('selectedCampaign')).toBeNull();
  expect(localStorage.getItem('accountType')).toBeNull();
  expect(screen.queryByTestId('campaign-menu')).not.toBeInTheDocument();
});

test('a shared session entering through a settlement URL returns to the map with campaign context', async () => {
  window.history.replaceState({}, '', '/settlementManager?campaignID=7&campaignName=Waterdeep&accountType=DM');
  axios.get.mockImplementation((url) => {
    if (url === '/api/session') return Promise.resolve({ data: { success: true, access_token: 'shared-token', id: 42, username: 'dm' } });
    return Promise.resolve({ data: {} });
  });

  render(<App />);

  expect(await screen.findByText('Settlement manager')).toBeInTheDocument();
  expect(window.location.pathname).toBe('/settlementManager');
  expect(localStorage.getItem('token')).toBe('shared-token');
  expect(screen.queryByText('Campaign picker')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('DM sound player')).not.toBeInTheDocument();
  expect(axios.get).not.toHaveBeenCalledWith('/api/sounds', expect.anything());
});

test('credential login preserves an explicit map campaign entry', async () => {
  window.history.replaceState({}, '', '/settlementManager?campaignID=7&campaignName=Waterdeep&accountType=DM');
  axios.get.mockRejectedValue({ response: { status: 401 } });
  axios.post.mockImplementation((url) => url === '/api/login'
    ? Promise.resolve({ data: { access_token: 'new-token', userID: 42, username: 'dm' } })
    : Promise.reject(new Error(`Unexpected request: ${url}`)));

  render(<App />);
  fireEvent.change(await screen.findByPlaceholderText('Username'), { target: { value: 'DM' } });
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Login' }));

  expect(await screen.findByText('Settlement manager')).toBeInTheDocument();
  expect(window.location.pathname).toBe('/settlementManager');
  expect(screen.queryByText('Campaign picker')).not.toBeInTheDocument();
});

test('a backend login failure is visible instead of failing silently', async () => {
  axios.post.mockImplementation((url) => url === '/api/login'
    ? Promise.reject({ response: { status: 500, data: {} } })
    : Promise.reject(new Error(`Unexpected request: ${url}`)));

  render(<App />);
  fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'user' } });
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Login' }));

  expect(await screen.findByText('The server could not complete the login request (HTTP 500).')).toBeInTheDocument();
});

test('a network login failure explains that the backend is unreachable', async () => {
  axios.post.mockImplementation((url) => url === '/api/login'
    ? Promise.reject(new Error('Network Error'))
    : Promise.reject(new Error(`Unexpected request: ${url}`)));

  render(<App />);
  fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'user' } });
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Login' }));

  expect(await screen.findByText('Unable to connect to the server backend. Check that it is running and try again.')).toBeInTheDocument();
});
