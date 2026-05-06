import type {JSX} from "react";

import {Navigate} from "react-router-dom";

export function ExplorePage(): JSX.Element {
  return <Navigate replace to="/" />;
}
