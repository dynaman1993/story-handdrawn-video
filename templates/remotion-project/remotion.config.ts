import {Config} from '@remotion/cli/config';
import {existsSync} from 'node:fs';

const browserCandidates = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
];
for (const p of browserCandidates) {
  if (existsSync(p)) {
    Config.setBrowserExecutable(p);
    break;
  }
}

Config.setConcurrency(1);
Config.setPublicDir('./public');
Config.setOverwriteOutput(true);
Config.setVideoImageFormat('jpeg');
