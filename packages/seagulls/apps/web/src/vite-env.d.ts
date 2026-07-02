/// <reference types="vite/client" />

interface Window {
  SEAGULL_CONFIG?: {
    socialApiUrl?: string;
    messageApiUrl?: string;
    aiProviderApiUrl?: string;
    adminDomainName?: string;
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
