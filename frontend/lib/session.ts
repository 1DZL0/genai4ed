"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, ApiError, type Me } from "@/lib/api";

/** One sign-in per role: a browser can be a teacher in one tab and a student in another. */
export const meKey = (role?: Me["role"]) => `auth/me/${role ?? "any"}`;

/** undefined: still asking, render nothing. null: signed out. Me: signed in. */
export function useMe(role?: Me["role"]): Me | null | undefined {
  const { data, error } = useSWR<Me>(meKey(role), () => api.me(role), {
    shouldRetryOnError: false,
  });
  if (error) return (error as ApiError).status === 401 ? null : undefined;
  return data;
}

export function homeFor(role: Me["role"]): string {
  return role === "teacher" ? "/teacher" : "/student";
}

/** For a page that belongs to one role: sends anyone else away and returns the user once allowed. */
export function useSignedIn(role: Me["role"]): Me | undefined {
  const me = useMe(role);
  const router = useRouter();

  useEffect(() => {
    if (me === null) router.replace(role === "teacher" ? "/login" : "/join");
    else if (me && me.role !== role) router.replace(homeFor(me.role));
  }, [me, role, router]);

  return me && me.role === role ? me : undefined;
}
