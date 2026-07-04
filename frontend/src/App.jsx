import Navbar from './components/Navbar';
import { Routes, Route } from 'react-router-dom';

import Home from './pages/Home';
import Dashboard from './pages/Dashboard';
import Explore from './pages/Explore';
import EmbeddingMap from './pages/EmbeddingMap';
import Docs from './pages/Docs';
import ScrollToHash from './components/ScrollToHash';

function App() {
  return (
    <div className="min-h-screen bg-[#0c0a09] text-white">

      <ScrollToHash />

      <Navbar />

      <main className="max-w-7xl mx-auto px-8 pt-20 pb-32">

        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/explore" element={<Explore />} />
          <Route path="/embedding-map" element={<EmbeddingMap />} />
          <Route path="/docs" element={<Docs />} />
        </Routes>

      </main>

    </div>
  );
}

export default App;