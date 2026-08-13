import { api } from "/scripts/api.js";
import { app } from "/scripts/app.js";

import { registerLlamaCppWidgetStates } from "./existing/llama-cpp-widget-states";
import { registerOllamaConnectivity } from "./existing/ollama-connectivity";
import { registerReferenceDirector } from "./reference-director/extension";
import referenceDirectorCss from "./reference-director/styles.css?inline";

const STYLE_ID = "ollama-image-list-reference-director-style";

function installStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = referenceDirectorCss;
  document.head.append(style);
}

installStyles();
registerOllamaConnectivity(app, api);
registerLlamaCppWidgetStates(app);
registerReferenceDirector(app, api);
