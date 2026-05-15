import { ToastProvider } from './components/ToastContext';
import { Workspace } from './pages/Workspace';

function App() {
  return (
    <ToastProvider>
      <Workspace />
    </ToastProvider>
  );
}

export default App;
