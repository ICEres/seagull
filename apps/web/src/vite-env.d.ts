/// <reference types="vite/client" />

interface Window {
  SEAGULL_CONFIG?: {
    socialApiUrl?: string;
    messageApiUrl?: string;
    auth?: {
      mode?: string;
      issuer?: string;
      hostedDomain?: string;
      clientId?: string;
      redirectUri?: string;
      logoutUri?: string;
    };
  };
}
