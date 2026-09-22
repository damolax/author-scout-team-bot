import { createAuthClient } from '@neondatabase/neon-js/auth'

export const NEON_AUTH_URL = 'https://ep-cool-lake-b5w5dfc2.neonauth.c-7.us-east-2.aws.neon.tech/author_scout_bot/auth'

export const authClient = createAuthClient(NEON_AUTH_URL)

export function sessionTokenFrom(data) {
  return data?.session?.token || data?.data?.session?.token || data?.token || data?.data?.token || ''
}
