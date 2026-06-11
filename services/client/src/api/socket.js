import { io } from 'socket.io-client'

const socket = io(import.meta.env.VITE_API_URL || '/', {
  transports: ['websocket', 'polling']
})

socket.on('connect_error', (err) => {
  console.error('Connection error:', err.message); // Logs "Invalid query string"
});

export { socket }
