import { api } from "../../scripts/api.js"
import { app } from "../../scripts/app.js"
import { registerLlamaCppRuntimeSettings } from "./llama-cpp-runtime-settings.ts"
import { registerLlamaCppServerSession } from "./llama-cpp-server-session.ts"
import { registerLlamaCppWidgetStates } from "./llama-cpp-widget-states.ts"
import { registerOllamaConnectivity } from "./ollama-connectivity.ts"

registerLlamaCppWidgetStates(app)
registerLlamaCppServerSession(app, api)
registerLlamaCppRuntimeSettings(app, api)
registerOllamaConnectivity(app, api)
