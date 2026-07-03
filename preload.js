"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  onUpdateReady: (cb) => {
    ipcRenderer.removeAllListeners("update-ready");
    ipcRenderer.on("update-ready", (_event) => cb());
  },
  installUpdate: () => ipcRenderer.send("install-update"),
  getUpdateReady: () => ipcRenderer.invoke("get-update-ready"),
});
