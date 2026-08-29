import { createContext, useContext, useMemo, useState } from "react";

const DemoSessionContext = createContext(null);

export function DemoSessionProvider({ children }) {
  const [poolId, setPoolId] = useState(null);
  const [demandSignalId, setDemandSignalId] = useState(null);

  const value = useMemo(
    () => ({ poolId, setPoolId, demandSignalId, setDemandSignalId }),
    [poolId, demandSignalId]
  );

  return (
    <DemoSessionContext.Provider value={value}>
      {children}
    </DemoSessionContext.Provider>
  );
}

export function useDemoSession() {
  const ctx = useContext(DemoSessionContext);
  if (!ctx) throw new Error("DemoSessionProvider missing");
  return ctx;
}

