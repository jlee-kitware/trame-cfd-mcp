// Example: Sending monitor data as a single-row table via Catalyst
//
// Each iteration sends ONE row with named columns.
// Column names are self-describing, so the pipeline script can
// handle changes in monitored quantities during the simulation.

#include <catalyst.hpp>
#include <catalyst_conduit.hpp>

// Option 1: Using Conduit directly (no VTK dependency)
void send_monitors_conduit(conduit::Node& node, int iteration, 
                           double res_continuity, double res_momentum, double res_energy,
                           double drag, double lift) {
    
    node["catalyst/state/timestep"] = iteration;
    
    // Table channel
    conduit::Node& monitors = node["catalyst/channels/monitors"];
    monitors["type"] = "object";
    
    conduit::Node& data = monitors["data"];
    data["num_rows"] = 1;
    
    // Each column is a single-element array
    // Using set() copies the data; use set_external() for zero-copy
    conduit::Node& cols = data["columns"];
    
    double iter_val = static_cast<double>(iteration);
    cols["iteration"].set(&iter_val, 1);
    cols["residual_continuity"].set(&res_continuity, 1);
    cols["residual_momentum"].set(&res_momentum, 1);
    cols["residual_energy"].set(&res_energy, 1);
    cols["drag"].set(&drag, 1);
    cols["lift"].set(&lift, 1);
}


// Option 2: Using VTK's vtkTable (if VTK available on simulation side)
#ifdef USE_VTK
#include <vtkNew.h>
#include <vtkTable.h>
#include <vtkFloatArray.h>
#include <vtkDataObjectToConduit.h>

void send_monitors_vtk(conduit::Node& node, int iteration,
                       double res_continuity, double res_momentum, double res_energy,
                       double drag, double lift) {
    
    node["catalyst/state/timestep"] = iteration;
    
    // Create a 1-row vtkTable
    vtkNew<vtkTable> table;
    
    // Helper to add a column
    auto addColumn = [&table](const char* name, double value) {
        vtkNew<vtkFloatArray> arr;
        arr->SetName(name);
        arr->SetNumberOfTuples(1);
        arr->SetValue(0, static_cast<float>(value));
        table->AddColumn(arr);
    };
    
    addColumn("iteration", static_cast<double>(iteration));
    addColumn("residual_continuity", res_continuity);
    addColumn("residual_momentum", res_momentum);
    addColumn("residual_energy", res_energy);
    addColumn("drag", drag);
    addColumn("lift", lift);
    
    // Convert vtkTable to Conduit node
    vtkNew<vtkDataObjectToConduit> converter;
    converter->SetInputDataObject(table);
    converter->Update();
    
    // Get the Conduit representation
    conduit::Node& tableNode = *converter->GetConduitNode();
    
    // Put in the Catalyst node
    node["catalyst/channels/monitors/type"] = "vtk";  // VTK data object
    node["catalyst/channels/monitors/data"].set(tableNode);
}
#endif


// Usage in your simulation:
//
// void timestep(int iter, Solver* solver) {
//     conduit::Node node;
//     
//     // Send mesh data (your existing adaptor code)
//     // ...
//     
//     // Add monitor data as a 1-row table
//     send_monitors_conduit(node, iter,
//         solver->residual_continuity,
//         solver->residual_momentum, 
//         solver->residual_energy,
//         solver->drag_coefficient,
//         solver->lift_coefficient);
//     
//     catalyst_execute(conduit::c_node(&node));
// }


// Dynamic columns example - add/remove monitored quantities during run
void send_monitors_dynamic(conduit::Node& node, int iteration,
                           const std::map<std::string, double>& monitors) {
    
    node["catalyst/state/timestep"] = iteration;
    
    conduit::Node& channel = node["catalyst/channels/monitors"];
    channel["type"] = "object";
    
    conduit::Node& data = channel["data"];
    data["num_rows"] = 1;
    
    conduit::Node& cols = data["columns"];
    
    // Add iteration column
    double iter_val = static_cast<double>(iteration);
    cols["iteration"].set(&iter_val, 1);
    
    // Add all monitor columns dynamically
    for (const auto& [name, value] : monitors) {
        cols[name].set(&value, 1);
    }
}

// Usage:
// std::map<std::string, double> monitors;
// monitors["residual_continuity"] = solver->res_cont;
// monitors["residual_momentum"] = solver->res_mom;
// if (solver->turbulence_enabled) {
//     monitors["residual_k"] = solver->res_k;
//     monitors["residual_omega"] = solver->res_omega;
// }
// send_monitors_dynamic(node, iter, monitors);
