"""
Catalyst pipeline that accumulates monitor data as a vtkTable.

The simulation sends a single-row vtkTable each iteration with named columns.
This script accumulates rows over time and creates a convergence chart.

SIMULATION SIDE (C++):
    // Create a 1-row table with named columns
    vtkNew<vtkTable> table;
    
    vtkNew<vtkFloatArray> iter;
    iter->SetName("iteration");
    iter->SetNumberOfTuples(1);
    iter->SetValue(0, current_iteration);
    table->AddColumn(iter);
    
    vtkNew<vtkFloatArray> resCont;
    resCont->SetName("residual_continuity");
    resCont->SetNumberOfTuples(1);
    resCont->SetValue(0, solver->res_continuity);
    table->AddColumn(resCont);
    
    // ... add more columns as needed
    
    // Convert to Conduit using VTK's bridge
    vtkNew<vtkDataObjectToConduit> converter;
    converter->SetInputDataObject(table);
    converter->Update();
    conduit::Node& tableNode = converter->GetConduitNode();
    
    // Put in the Catalyst node
    node["catalyst/channels/monitors/type"] = "table";
    node["catalyst/channels/monitors/data"].set_external(tableNode);

OR using raw Conduit (no VTK on sim side):
    
    // Table as Conduit - column-oriented
    node["catalyst/channels/monitors/type"] = "object";
    node["catalyst/channels/monitors/data/num_rows"] = 1;
    node["catalyst/channels/monitors/data/columns/iteration"].set(&current_iter, 1);
    node["catalyst/channels/monitors/data/columns/residual_continuity"].set(&res_cont, 1);
    node["catalyst/channels/monitors/data/columns/residual_momentum"].set(&res_mom, 1);
    node["catalyst/channels/monitors/data/columns/drag"].set(&Cd, 1);
    node["catalyst/channels/monitors/data/columns/lift"].set(&Cl, 1);
"""

from paraview.catalyst import Options

# Enable Live visualization
options = Options()
options.EnableCatalystLive = True
options.CatalystLiveURL = "localhost:22222"

# Accumulated table (persists across catalyst_execute calls)
_accumulated_table = None
_chart_view = None
_display = None


def catalyst_execute(info):
    """Called each timestep - accumulate table row."""
    global _accumulated_table, _chart_view, _display
    
    from paraview import simple
    import vtk
    
    timestep = info.timestep
    
    try:
        params = info.catalyst_params
        
        if not params.has_path("channels/monitors/data/columns"):
            # No monitor data this iteration
            return
        
        columns_node = params["channels/monitors/data/columns"]
        
        # Get column names from the incoming data
        column_names = []
        for i in range(columns_node.number_of_children()):
            column_names.append(columns_node.child(i).name())
        
        # Initialize accumulated table if needed
        if _accumulated_table is None:
            _accumulated_table = vtk.vtkTable()
            for name in column_names:
                arr = vtk.vtkFloatArray()
                arr.SetName(name)
                _accumulated_table.AddColumn(arr)
        
        # Check for new columns (residuals added/removed during run)
        existing_names = set()
        for i in range(_accumulated_table.GetNumberOfColumns()):
            existing_names.add(_accumulated_table.GetColumn(i).GetName())
        
        for name in column_names:
            if name not in existing_names:
                # New column appeared - add it with NaN padding
                arr = vtk.vtkFloatArray()
                arr.SetName(name)
                arr.SetNumberOfTuples(_accumulated_table.GetNumberOfRows())
                for j in range(arr.GetNumberOfTuples()):
                    arr.SetValue(j, float('nan'))
                _accumulated_table.AddColumn(arr)
                print(f"[Monitor] New column detected: {name}")
        
        # Append new row
        row_idx = _accumulated_table.GetNumberOfRows()
        _accumulated_table.SetNumberOfRows(row_idx + 1)
        
        for name in column_names:
            col = _accumulated_table.GetColumnByName(name)
            if col is not None:
                value = columns_node[name].value()
                if hasattr(value, '__len__'):
                    value = value[0]  # Single element array
                col.SetValue(row_idx, float(value))
        
        # Fill missing columns with NaN
        for i in range(_accumulated_table.GetNumberOfColumns()):
            col = _accumulated_table.GetColumn(i)
            if col.GetName() not in column_names:
                col.SetValue(row_idx, float('nan'))
        
        # Update chart every 10 iterations
        if timestep > 0 and timestep % 10 == 0:
            _update_chart()
            
    except Exception as e:
        import traceback
        print(f"[Monitor] Error at timestep {timestep}: {e}")
        traceback.print_exc()
    
    # Print status periodically
    if timestep % 50 == 0 and _accumulated_table is not None:
        n_rows = _accumulated_table.GetNumberOfRows()
        n_cols = _accumulated_table.GetNumberOfColumns()
        col_names = [_accumulated_table.GetColumn(i).GetName() for i in range(n_cols)]
        print(f"[Monitor] Iter {timestep}: {n_rows} rows, columns: {col_names}")


def _update_chart():
    """Create or update the residual chart."""
    global _chart_view, _display
    
    from paraview import simple
    
    if _accumulated_table is None or _accumulated_table.GetNumberOfRows() == 0:
        return
    
    # Create TrivialProducer to hold our table
    producer = simple.TrivialProducer(registrationName="MonitorTable")
    producer.GetClientSideObject().SetOutput(_accumulated_table)
    producer.UpdatePipeline()
    
    # Create chart view if needed
    if _chart_view is None:
        _chart_view = simple.CreateXYPlotView()
        _chart_view.ViewSize = [800, 400]
        _chart_view.ChartTitle = 'Residual Convergence'
        _chart_view.BottomAxisTitle = 'Iteration'
        _chart_view.LeftAxisTitle = 'Residual'
        _chart_view.LeftAxisLogScale = 1
        
        _display = simple.Show(producer, _chart_view)
        _display.XArrayName = 'iteration'
        _display.UseIndexForXAxis = 0
        
        # Show all residual columns
        visible = []
        for i in range(_accumulated_table.GetNumberOfColumns()):
            name = _accumulated_table.GetColumn(i).GetName()
            if name.startswith('residual'):
                visible.append(name)
        _display.SeriesVisibility = visible
    
    simple.Render(_chart_view)


def get_accumulated_table():
    """Get the accumulated vtkTable (for external access)."""
    return _accumulated_table


def get_column_names():
    """Get list of column names in the accumulated table."""
    if _accumulated_table is None:
        return []
    return [_accumulated_table.GetColumn(i).GetName() 
            for i in range(_accumulated_table.GetNumberOfColumns())]
