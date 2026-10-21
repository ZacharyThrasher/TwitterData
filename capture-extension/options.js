const input = document.getElementById("port");
chrome.storage.local.get({ port: 8765 }).then(({ port }) => { input.value = port; });
document.getElementById("save").addEventListener("click", () => {
  const port = Number(input.value);
  chrome.storage.local.set({ port }).then(() => { document.getElementById("msg").textContent = "Saved"; });
});
