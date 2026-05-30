const assert = require('node:assert/strict');
const test = require('node:test');

const {
  isWindowsAppsPython,
  selectPythonExecutable,
} = require('../scripts/lib/python-resolver.cjs');

test('detects WindowsApps python execution aliases', () => {
  assert.equal(
    isWindowsAppsPython('C:\\Users\\qi\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe'),
    true
  );
  assert.equal(isWindowsAppsPython('D:\\conda\\python.exe'), false);
});

test('selects the first usable non-WindowsApps python executable', async () => {
  const chosen = await selectPythonExecutable(
    [
      'C:\\Users\\qi\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe',
      'D:\\conda\\python.exe',
    ],
    async (candidate) => candidate === 'D:\\conda\\python.exe'
  );

  assert.equal(chosen, 'D:\\conda\\python.exe');
});

test('returns null when every candidate is a shim or unusable', async () => {
  const chosen = await selectPythonExecutable(
    [
      'C:\\Users\\qi\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe',
      'D:\\broken\\python.exe',
    ],
    async () => false
  );

  assert.equal(chosen, null);
});
