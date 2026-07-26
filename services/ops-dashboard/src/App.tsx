import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { OverviewPage } from "./pages/OverviewPage";
import { OrdersPage } from "./pages/OrdersPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { InventoryPage } from "./pages/InventoryPage";
import { SagaMonitorPage } from "./pages/SagaMonitorPage";
import { DeadLetterQueuePage } from "./pages/DeadLetterQueuePage";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { DataQualityPage } from "./pages/DataQualityPage";
import { DataPlatformPage } from "./pages/DataPlatformPage";
import { ForecastingPage } from "./pages/ForecastingPage";
import { FailureLabPage } from "./pages/FailureLabPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/:orderId" element={<OrderDetailPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="saga-monitor" element={<SagaMonitorPage />} />
        <Route path="dead-letters" element={<DeadLetterQueuePage />} />
        <Route path="observability" element={<ObservabilityPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="data-platform" element={<DataPlatformPage />} />
        <Route path="forecasting" element={<ForecastingPage />} />
        <Route path="failure-lab" element={<FailureLabPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
