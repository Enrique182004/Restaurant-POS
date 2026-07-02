"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  onUpdateReady: (cb) => ipcRenderer.on("update-ready", (_event) => cb()),
  installUpdate: () => ipcRenderer.send("install-update"),
});
