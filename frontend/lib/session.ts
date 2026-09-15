"use client";

/**
 * Who is signed in, as far as the backend is concerned.
 *
 * The cookie is HttpOnly, so the page cannot inspect it; it asks `/api/auth/me`
 * instead. Three states, and the difference matters:
 *
 *   undefined  still asking. Render nothing; conclude nothing.
 *   null       not signed in.
 *   Me         signed in.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, ApiError, type Me } from "@/lib/api";

export const ME_KEY = "auth/me";

export function useMe(): Me | null | undefined {
  const { data, error } = useSWR<Me>(ME_KEY, api.me, { shouldRetryOnError: false });
  if (error) return (error as ApiError).status === 401 ? null : undefined;
  return data;
}

export function homeFor(role: Me["role"]): string {
  return role === "teacher" ? "/teacher" : "/student";
}

/**
 * For pages that belong to one role. Sends anyone else to where they should
 * be - the front door if signed out, their own home if the wrong role - and
 * returns the signed-in user only once they are allowed to see the page.
 */
export function useSignedIn(role: Me["role"]): Me | undefined {
  const me = useMe();
  const router = useRouter();

  useEffect(() => {
    if (me === null) router.replace(role === "teacher" ? "/login" : "/join");
    else if (me && me.role !== role) router.replace(homeFor(me.role));
  }, [me, role, router]);

  return me && me.role === role ? me : undefined;
}
