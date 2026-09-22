import { createAuthClient } from 'better-auth/client'

export const NEON_AUTH_URL = 'https://ep-cool-lake-b5w5dfc2.neonauth.c-7.us-east-2.aws.neon.tech/author_scout_bot/auth'

export const authClient = createAuthClient({
  baseURL: NEON_AUTH_URL,
})

export function sessionTokenFrom(value) {
  const data=value?.data ?? value
  return data?.session?.token || data?.token || ''
}
