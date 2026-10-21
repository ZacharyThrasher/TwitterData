// Posts thread views to the local helper on 127.0.0.1. Nothing goes anywhere else.
// Clicking the toolbar button pauses or resumes recording.

function showState(paused) {
  chrome.action.setBadgeText({ text: paused ? "OFF" : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#a33a2b" });
  chrome.action.setTitle({ title: paused ? "Capture recorder: PAUSED. Click to resume."
                                         : "Capture recorder: ON. Click to pause." });
}

chrome.runtime.onStartup.addListener(() => chrome.storage.local.get({ paused: false }).then(s => showState(s.paused)));
chrome.runtime.onInstalled.addListener(() => chrome.storage.local.get({ paused: false }).then(s => showState(s.paused)));

chrome.action.onClicked.addListener(async () => {
  const { paused } = await chrome.storage.local.get({ paused: false });
  await chrome.storage.local.set({ paused: !paused });
  showState(!paused);
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || msg.type !== "save") return false;
  chrome.storage.local.get({ port: 8765, paused: false })
    .then(({ port, paused }) => {
      if (paused) return { paused: true };
      return fetch(`http://127.0.0.1:${port}/api/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(msg.payload),
      }).then(r => r.json());
    })
    .then(reply)
    .catch(() => reply({ error: "helper_unreachable" }));
  return true; // reply arrives asynchronously
});
