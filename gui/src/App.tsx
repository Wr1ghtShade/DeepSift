import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Route, Router, Switch } from "wouter";
import { UNAUTHORIZED_EVENT, api } from "./api";
import { Shell } from "./components/Shell";
import { aroundNav } from "./nav";
import { EntityPage } from "./pages/Entity";
import { InvestigationsPage } from "./pages/Investigations";
import { LoginPage } from "./pages/Login";
import { NewSearchPage } from "./pages/NewSearch";
import { NotFoundPage } from "./pages/NotFound";
import { ResultsPage } from "./pages/Results";
import { ServicesPage } from "./pages/Services";
import { SettingsPage } from "./pages/Settings";

export function App() {
  const client = useQueryClient();
  const session = useQuery({ queryKey: ["session"], queryFn: api.session, staleTime: Infinity });

  useEffect(() => {
    const expired = () => client.setQueryData(["session"], { authenticated: false });
    window.addEventListener(UNAUTHORIZED_EVENT, expired);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired);
  }, [client]);

  if (session.isPending) {
    return (
      <div className="login" aria-busy="true">
        <div className="spinner" role="status" aria-label="Chargement" />
      </div>
    );
  }
  if (!session.data?.authenticated) return <LoginPage />;

  return (
    <Router aroundNav={aroundNav}>
      <Shell>
        <Switch>
          <Route path="/" component={NewSearchPage} />
          <Route path="/investigations" component={InvestigationsPage} />
          <Route path="/investigations/:id" component={ResultsPage} />
          <Route path="/entities/:id" component={EntityPage} />
          <Route path="/services" component={ServicesPage} />
          <Route path="/settings" component={SettingsPage} />
          <Route component={NotFoundPage} />
        </Switch>
      </Shell>
    </Router>
  );
}
