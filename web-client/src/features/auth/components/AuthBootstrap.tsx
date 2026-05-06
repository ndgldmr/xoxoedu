import {useEffect} from "react";

import {setAuthFailureHandler} from "../../../lib/api/client";
import {useAuthStore} from "../store/useAuthStore";

interface AuthBootstrapProps {
  readonly enabled: boolean;
}

export function AuthBootstrap({enabled}: AuthBootstrapProps): null {
  const bootstrap = useAuthStore((state) => state.bootstrap);
  const markAnonymous = useAuthStore((state) => state.markAnonymous);

  useEffect(() => {
    setAuthFailureHandler(markAnonymous);
    return () => {
      setAuthFailureHandler(null);
    };
  }, [markAnonymous]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    void bootstrap();
  }, [bootstrap, enabled]);

  return null;
}
