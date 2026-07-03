"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  onUpdateReady: (cb) => {
    ipcRenderer.removeAllListeners("update-ready");
    ipcRenderer.on("update-ready", (_event) => cb());
  },
  onUpdateStatus: (cb) => {
    ipcRenderer.removeAllListeners("update-status");
    ipcRenderer.on("update-status", (_event, data) => cb(data));
  },
  installUpdate: () => ipcRenderer.send("install-update"),
  getUpdateReady: () => ipcRenderer.invoke("get-update-ready"),
  checkForUpdatesNow: () => ipcRenderer.invoke("check-for-updates-now"),
});
