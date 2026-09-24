import { createContext, useContext } from 'react'

export interface Session {
  /** start_param, проверенный бэкендом вместе с подписью initData. */
  startParam: string | null
  inMax: boolean
}

export const SessionContext = createContext<Session | null>(null)

export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession вне AuthGate')
  return session
}
