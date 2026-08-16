import { api } from "../../scripts/api.js"
import { app } from "../../scripts/app.js"
import { registerLlamaCppWidgetStates } from "./llama-cpp-widget-states.ts"
import { registerOllamaConnectivity } from "./ollama-connectivity.ts"

registerLlamaCppWidgetStates(app)
registerOllamaConnectivity(app, api)
