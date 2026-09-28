type RuntimeMessages = {
  checking: string
  statusLoadFailure: string
  startFailureSummary: (projectName: string) => string
  startFailureFallback: string
  saveFailureSummary: (projectName: string) => string
  unknownError: string
}

const messages: Record<string, RuntimeMessages> = {
  en: {
    checking: "Checking...",
    statusLoadFailure: "Could not load runtime status",
    startFailureSummary: (projectName) =>
      `${projectName} could not start the llama.cpp server`,
    startFailureFallback: "The llama server process is not running.",
    saveFailureSummary: (projectName) =>
      `${projectName} could not save the llama.cpp setting`,
    unknownError: "Unknown error.",
  },
  ko: {
    checking: "확인 중...",
    statusLoadFailure: "런타임 상태를 불러오지 못했습니다",
    startFailureSummary: (projectName) =>
      `${projectName} llama.cpp 서버를 시작하지 못했습니다`,
    startFailureFallback: "llama server 프로세스가 실행 중이 아닙니다.",
    saveFailureSummary: (projectName) =>
      `${projectName} llama.cpp 설정을 저장하지 못했습니다`,
    unknownError: "알 수 없는 오류입니다.",
  },
}

export function getRuntimeMessages(locale: string | undefined): RuntimeMessages {
  const language = locale?.replace("_", "-").split("-")[0]?.toLowerCase()
  return messages[language ?? ""] ?? messages.en
}
