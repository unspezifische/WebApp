import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

import CampaignSettings from './CampaignSettings';

jest.mock('axios');

const initialSettings = {
  campaign: { id: 5, name: 'Test Campaign', system: 'D&D', ruleset: '5e', rules_system: 'D&D 5e', icon: null },
  installed_modules: [],
  available_modules: [],
  calendar: null,
  profile_icon_presets: [
    { key: 'wizard', name: 'Wizard', url: '/avatars/wizard.webp' },
  ],
};

beforeEach(() => jest.resetAllMocks());

test('the DM can rename the campaign', async () => {
  axios.get.mockResolvedValue({ data: initialSettings });
  axios.patch.mockResolvedValue({
    data: { campaign: { ...initialSettings.campaign, name: 'Waterdeep Nights' } },
  });
  const updated = jest.fn();
  window.addEventListener('campaign-updated', updated);

  render(<CampaignSettings campaignID={5} headers={{ Authorization: 'Bearer token' }} embedded />);

  fireEvent.change(await screen.findByLabelText('Campaign name'), { target: { value: 'Waterdeep Nights' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save name' }));

  await waitFor(() => expect(axios.patch).toHaveBeenCalledWith(
    '/api/campaigns/5/name',
    { name: 'Waterdeep Nights' },
    { headers: { Authorization: 'Bearer token' } },
  ));
  expect(await screen.findByText('Campaign renamed to Waterdeep Nights.')).toBeInTheDocument();
  expect(updated).toHaveBeenCalled();
  window.removeEventListener('campaign-updated', updated);
});

test('the DM can choose a preloaded campaign profile icon', async () => {
  axios.get.mockResolvedValue({ data: initialSettings });
  axios.patch.mockResolvedValue({
    data: { campaign: { ...initialSettings.campaign, icon: '/avatars/wizard.webp' } },
  });

  render(<CampaignSettings campaignID={5} headers={{ Authorization: 'Bearer token' }} embedded />);

  fireEvent.click(await screen.findByRole('button', { name: 'Use Wizard campaign icon' }));

  await waitFor(() => expect(axios.patch).toHaveBeenCalledWith(
    '/api/campaigns/5/profile-icon',
    { preset_key: 'wizard' },
    { headers: { Authorization: 'Bearer token' } },
  ));
  expect(await screen.findByText('Campaign profile icon updated.')).toBeInTheDocument();
  expect(screen.getByAltText('Current campaign icon')).toHaveAttribute('src', '/avatars/wizard.webp');
});

test('the DM can choose the D&D ruleset independently of the system', async () => {
  axios.get.mockResolvedValue({ data: initialSettings });
  axios.patch.mockResolvedValue({
    data: { campaign: { ...initialSettings.campaign, ruleset: '5e (2024)', rules_system: 'D&D 5e (2024)' } },
  });

  render(<CampaignSettings campaignID={5} headers={{ Authorization: 'Bearer token' }} embedded />);

  fireEvent.change(await screen.findByLabelText('Edition'), { target: { value: '5e (2024)' } });

  await waitFor(() => expect(axios.patch).toHaveBeenCalledWith(
    '/api/campaigns/5/ruleset',
    { ruleset: '5e (2024)' },
    { headers: { Authorization: 'Bearer token' } },
  ));
  expect(await screen.findByText('Campaign ruleset changed to 5e (2024).')).toBeInTheDocument();
});

test('an installed module can import newly packaged NPC content', async () => {
  const settings = {
    ...initialSettings,
    installed_modules: [{
      id: 3,
      module_key: 'waterdeep_dragon_heist',
      module_name: 'Waterdeep Dragon Heist',
      setting_key: 'forgotten_realms',
      starting_year: 1492,
      settlement_strategy: 'merge',
    }],
  };
  axios.get.mockResolvedValue({ data: settings });
  axios.post.mockResolvedValue({ data: { npcs_added: 37, settlement_result: 'merged' } });

  render(<CampaignSettings campaignID={5} headers={{ Authorization: 'Bearer token' }} embedded />);

  fireEvent.click(await screen.findByRole('button', { name: 'Refresh content' }));

  await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
    '/api/campaigns/5/modules/waterdeep_dragon_heist/refresh',
    { settlement_strategy: 'merge' },
    { headers: { Authorization: 'Bearer token' } },
  ));
  expect(await screen.findByText('Waterdeep Dragon Heist refreshed. 37 new NPCs added to the library.')).toBeInTheDocument();
});
