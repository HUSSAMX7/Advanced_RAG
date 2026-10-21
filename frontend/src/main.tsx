import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import IdentityGate from './components/IdentityGate'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <IdentityGate><App /></IdentityGate>
  </React.StrictMode>,
)
