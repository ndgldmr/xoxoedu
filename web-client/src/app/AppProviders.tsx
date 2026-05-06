import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import React from "react";
import {RouterProvider} from "react-router-dom";
import {Toaster} from "sonner";

import {AuthBootstrap} from "../features/auth/components/AuthBootstrap";

interface AppProvidersProps {
  readonly bootstrap?: boolean;
  readonly router: React.ComponentProps<typeof RouterProvider>["router"];
}

export function AppProviders({bootstrap = true, router}: AppProvidersProps): React.JSX.Element {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrap enabled={bootstrap} />
      <RouterProvider router={router} />
      <Toaster position="top-right" richColors />
    </QueryClientProvider>
  );
}
