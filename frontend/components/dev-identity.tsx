"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { getPseudonym, setPseudonym } from "@/lib/identity";

/**
 * Seeds the browser's identity from `?as=`, so a link can be opened directly
 * as a given pseudonym.
 *
 * Development only, and it grants nothing: the backend already trusts whatever
 * pseudonym the browser sends, so this changes convenience and not privilege.
 * It disappears with the development identity seam.
 */
function Gate() {
  const params = useSearchParams();
  const as = params.get("as");

  useEffect(() => {
    if (as && as !== getPseudonym()) setPseudonym(as);
  }, [as]);

  return null;
}

export function DevIdentityGate() {
  return (
    <Suspense fallback={null}>
      <Gate />
    </Suspense>
  );
}
