import logging

import numpy as np
import copy
import warnings
import json, utilities

from neuron_methods import GLIFNeuronMethod, METHOD_LIBRARY

class GLIFNeuron( object ):    
    '''Generalized Linear Integrate and Fire neuron
    '''
    

    
    TYPE = "GLIF"

    def __init__(self, El, dt, tau, R_input, C, asc_vector, spike_cut_length, th_inf, coeffs,
                 AScurrent_dynamics_method, voltage_dynamics_method, threshold_dynamics_method,
                 AScurrent_reset_method, voltage_reset_method, threshold_reset_method): 
        self.type = GLIFNeuron.TYPE
        self.El = El
        self.dt = dt
        self.tau = np.array(tau)
        self.R_input = R_input
        self.C = C
        self.asc_vector = np.array(asc_vector)
        self.spike_cut_length = spike_cut_length
        self.th_inf = th_inf

        assert len(tau) == len(asc_vector), Exception("After-spike current vector must have same length as tau (%d vs %d)" % (asc_vector, tau))

        # values computed based on inputs
        self.k = 1.0 / self.tau
        self.G = 1.0 / self.R_input

        # Values that can be fit: They scale the input values.  
        # These are allowed to have default values because they are going to get optimized.
        self.coeffs = {
            'th_inf': 1,
            'C': 1,
            'G': 1,
            'b': 1,
            'a': 1,
            'asc_vector': np.ones(len(self.tau))
        }

        self.coeffs.update(coeffs)
        
        logging.debug('spike cut length: %d' %  self.spike_cut_length)

        # initialize dynamics methods
        self.AScurrent_dynamics_method = self.configure_library_method('AScurrent_dynamics_method', AScurrent_dynamics_method)
        self.voltage_dynamics_method = self.configure_library_method('voltage_dynamics_method', voltage_dynamics_method)
        self.threshold_dynamics_method = self.configure_library_method('threshold_dynamics_method', threshold_dynamics_method)

        # initialize reset methods
        self.AScurrent_reset_method = self.configure_library_method('AScurrent_reset_method', AScurrent_reset_method)
        self.voltage_reset_method = self.configure_library_method('voltage_reset_method', voltage_reset_method)
        self.threshold_reset_method = self.configure_library_method('threshold_reset_method', threshold_reset_method)

    def __str__(self):
        return json.dumps(self.to_dict(), default=utilities.json_handler)

    def to_dict(self):
        return {
            'type': self.type,
            'El': self.El,
            'dt': self.dt,
            'tau': self.tau,
            'R_input': self.R_input,
            'C': self.C,
            'spike_cut_length': self.spike_cut_length,
            'th_inf': self.th_inf,
            'coeffs': self.coeffs,
            'AScurrent_dynamics_method': self.AScurrent_dynamics_method,
            'voltage_dynamics_method': self.voltage_dynamics_method,
            'threshold_dynamics_method': self.threshold_dynamics_method,
            'AScurrent_reset_method': self.AScurrent_reset_method,
            'voltage_reset_method': self.voltage_reset_method,
            'threshold_reset_method': self.threshold_reset_method
        }

    def configure_method(self, method_name, method, method_params):
        return GLIFNeuronMethod(method_name, method, method_params)

    def configure_library_method(self, method_type, params):
        method_options = METHOD_LIBRARY.get(method_type, None)

        assert method_options is not None, Exception("Unknown method type (%s)" % method_type)
        
        method_name = params.get('name', None)
        method_params = params.get('params', None)
        
        assert method_name is not None, Exception("Method configuration for %s has no 'name'" % (method_type))
        assert method_params is not None, Exception("Method configuration for %s has no 'params'" % (method_params))
        
        method = method_options.get(method_name, None)
        
        assert method is not None, Exception("unknown method name %s of type %s" % (method_name, method_type))
        
        return self.configure_method(method_name, method, method_params)

    def dynamics(self, voltage_t0, threshold_t0, AScurrents_t0, inj, time_step, spike_time_steps):    
        '''Impliments the current based Mihalas Neiber GLIF neuron calculating variable 
        values (voltage, threshold and after spike currents) at 1 time step.
        Inputs:
            voltage_t0: scalar value of voltage threshold 
            threshold_t0: scalar value of voltage threshold
            AScurrents_t0: vector of scalar values for the after spike currents
            inj: scalar value of external current injection at one time step
        Returns: the scalar voltage (voltage_t1), scalar voltage threshold 
           (threshold_t1), and a array of scalar after spike currents (AScurrents_t1)
           as the result of the initial values and a current injection.
        '''

        AScurrents_t1 = self.AScurrent_dynamics_method(self, AScurrents_t0, time_step, spike_time_steps)
        voltage_t1 = self.voltage_dynamics_method(self, voltage_t0, AScurrents_t0, inj)
        threshold_t1 = self.threshold_dynamics_method(self, threshold_t0, voltage_t0)

        return voltage_t1, threshold_t1, AScurrents_t1
    
        
    #-------------------------------------------------------------------
    #----------RESET RULES----------------------------------------------
    #-------------------------------------------------------------------
    def reset(self, voltage_t0, threshold_t0, AScurrents_t0, t):
        '''The purpose is to reset the variables of the Mihalas-Neiber neuron.  Note: In Stefan's original code their are 
        2 MNupdate functions with the only difference being the t variable (where in one it was t and the other it
        was neuron.dt) to used when the times were found in the grid versus extrapolation.  Here I just have one function
        where the dt has to be entered  
        Inputs:
           p:  contains a bunch of neuron values
           param: parameters [C, G, a, ie, ii] correspond to the parameters in Stefan's paper
           var_in: [v,th,ie,ii]: variables that are evolving in time
           dt: delta t of each time step
        Returns:
           reset values of scalar voltage (voltage_t1), scalar threshold (threshold_t1), and an array
             of the after spike currents (AScurrents_t1) after there is a spike'''
        
        AScurrents_t1 = self.AScurrent_reset_method(self, AScurrents_t0, t)  #TODO: David I think you want to feed in r here
        voltage_t1 = self.voltage_reset_method(self, voltage_t0)
        threshold_t1 = self.threshold_reset_method(self, threshold_t0, voltage_t1)

        assert voltage_t1 < threshold_t1, Exception("Voltage reset above threshold: time step (%f) voltage (%f) reset (%f)" % (t, voltage_t1, threshold_t1))

        return voltage_t1, threshold_t1, AScurrents_t1
    


    #-----------------------------------------------------------------------------------
    #------------run functions----------------------------------------------------------
    #-----------------------------------------------------------------------------------
    def run(self, voltage_t0, threshold_t0, AScurrents_t0, stim):
        '''Steps though dynamics equations.  After each step check if threshold is larger than 
        voltage.  If it is the next values in the train are set to reset values.  NANS may or may 
        not be injected based on flag that specifies if spikes are cut.
        
        @param voltage_t0: scalar voltage that the model starts at
        @param threshold_t0: scalar threshold the modeinterpolatedSpikeVoltage_list, interpolated_spike_threshold_listl starts at  TODO: elaborate on this
        @param AScurrents_t0: vector of initial scalar values of after spike currents
        @param stim: vector of scalar current values
        @return: tuple of voltage_out scalar and grid_spike_time  TODO: elaborate on this
        '''

        num_time_steps = len(stim) 
        num_AScurrents = len(AScurrents_t0)
        
        # pre-allocate the output voltages, thresholds, and after-spike currents
        voltage_out=np.empty(num_time_steps)
        voltage_out[:]=np.nan
        threshold_out=np.empty(num_time_steps)
        threshold_out[:]=np.nan
        AScurrents_out=np.empty(shape=(num_time_steps, num_AScurrents))
        AScurrents_out[:]=np.nan        

        # array that will hold spike indices
        spike_time_steps = []
        spike_times = []
        interpolated_spike_times = []
        interpolated_spike_voltages = []
        interpolated_spike_thresholds = []

        time_step = 0
        while time_step < num_time_steps:
            if time_step % 10000 == 0:
                logging.info("time step %d / %d" % (time_step,  num_time_steps))

            # compute voltage, threshold, and ascurrents at current time step
            (voltage_t1, threshold_t1, AScurrents_t1) = self.dynamics(voltage_t0, threshold_t0, AScurrents_t0, stim[time_step], time_step, spike_time_steps) 

            #if the voltage is bigger than the threshold record the spike and reset the values
            if voltage_t1 > threshold_t1: 
                '''
                THINK ABOUT DEFINITION HERE SHOULD THE SPIKE BE COUNTED AND RESET BE DEFINED AND HOW THAT WILL AFFECT THE 
                CALCULATION IN REFERENCE TO THE SPIKES. OPTIONS ARE:
                        1. THRESHOLD IS ABOVE, THAT PRESENT VALUE GETS SET TO RESET AND THE INDEX IS COUNTED AT PRESENT POINT
                            Rational: at some point before the present value the voltage crossed threshold.  So the present point 
                            should be reset, the spike index should be set to the present value. The interpolated time would be 
                            before the present spike.  In this case when running the run_until_spike
                            would you have to let it run one extra ind to see if it spikes? (this is the method I am using now).
                        2. THRESHOLD IS ABOVE, THE NEXT VALUE GETS SET TO RESET AND THE INDEX IS COUNTED AT THE PRESENT POINT
                            Rational: Here the the voltage above threshold gets recorded and the spikeInd is recorded at the 
                            present ind, and the reset is at the next ind.  In this case the interpolated time will be before 
                            the spike ind. Would you be getting an extra spike here? 
                        3. THRESHOLD IS ABOVE, THE NEXT VALUE GETS SET TO RESET AND THE INDEX IS COUNTED AT THE NEXT POINT.
                            Rational:  I don't this this makes sense.  since the spike really happened at least at the index
                            before the reset and actually sometime before that.
                '''
                # spike_time_steps are stimulus indices when voltage surpassed threshold
                spike_time_steps.append(time_step)
                spike_times.append(time_step * self.dt) 

                # compute higher fidelity spike time/voltage/threshold by linearly interpolating 
                interpolated_spike_times.append(self.dt*(time_step+(threshold_t0-voltage_t0)/(voltage_t1-threshold_t1-voltage_t0+threshold_t0))) #estimate non grid spike time removed -1 4-22
                interpolated_spike_voltages.append(voltage_t0+(voltage_t1-voltage_t0)*(interpolated_spike_times[-1]-(time_step-1)*self.dt)/self.dt)
                interpolated_spike_thresholds.append(threshold_t0+(threshold_t1-threshold_t0)*(interpolated_spike_times[-1]-(time_step-1)*self.dt)/self.dt)
            
                # reset voltage, threshold, and after-spike currents
                (voltage_t0, threshold_t0, AScurrents_t0) = self.reset(voltage_t1, threshold_t1, AScurrents_t1, time_step) 

                # if we are not integrating during the spike (which includes right now), insert nans then jump ahead
                if self.spike_cut_length > 0:
                    n = self.spike_cut_length
                    voltage_out[time_step:time_step+n] = np.nan
                    threshold_out[time_step:time_step+n] = np.nan
                    AScurrents_out[time_step:time_step+n,:] = np.nan

                    time_step += self.spike_cut_length
                else:
                    # we are integrating during the spike, so store the reset values
                    voltage_out[time_step] = voltage_t0 
                    threshold_out[time_step] = threshold_t0
                    AScurrents_out[time_step,:] = AScurrents_t0

                    time_step += 1
            else:
                # there was no spike, store the next voltages
                voltage_out[time_step] = voltage_t1 
                threshold_out[time_step] = threshold_t1
                AScurrents_out[time_step,:] = AScurrents_t1

                voltage_t0 = voltage_t1
                threshold_t0 = threshold_t1
                AScurrents_t0 = AScurrents_t1
                
                time_step += 1

        return voltage_out, threshold_out, AScurrents_out, np.array(spike_times), np.array(interpolated_spike_times), np.array(spike_time_steps), np.array(interpolated_spike_voltages), np.array(interpolated_spike_thresholds)


    def run_wrt_target_spike_train(self, voltage_t0, threshold_t0, AScurrents_t0, stim, spike_train_ids, target_spike_exists, interpolated_spike_times):
        '''this functions takes an array of spike time indices and runs the model from where each of the spikes happen
        input:
            voltage_t0: scalar of the initial voltage
            threshold_t0: scalar of initial threshold
            AScurrents_t0: array of initial after spike currents
            stim:  array with the stimulus at each time
            spike_train_ids: array of indices of the spikes (in reference to the local stimulus) that will be the start points for the model
            target_spike_exists: True or False value.  If there is only one spike in spike_train_ids, True denotes that this was a real spike,
                False means that the spike was inserted at the end of the current injection for reference error calculations.
            interpolated_spike_times: array of interpolated spike times of the target trace
        Output
            actualTimeArray: an array of the actual times of the spikes. NOTE: THESE TIMES ARE CALCULATED BY ADDING THE TIME OF 
            THE INDIVIDUAL SPIKE TO THE TIME OF THE LAST SPIKE. 
            gridTimeArray: an array of the time of the spikes with the grid time precision.NOTE: THESE TIMES ARE CALCULATED BY A
            ADDING THE TIME OF THE INDIVIDUAL SPIKE TO THE TIME OF THE LAST SPIKE.
            voltage: array of voltage values. NOTE: IF THE MODEL NEURON SPIKES BEFORE THE TARGET THE VOLTAGE WILL 
                NOT BE CALCULATED THEREFORE THE RESULTING VECTOR WILL NOT BE AS LONG AS THE TARGET AND ALSO WILL NOT 
                MAKE SENSE WITH THE STIMULUS UNLESS YOU CUT IT AND OUTPUT IT TOO.
            gridISIFromLastTargSpike_array:  array of spike times of the model in reference to the last target (biological) spike 
                (not in reference to sweep start)
            voltageOfModelAtGridBioSpike_array:  array of scalars that contain the voltage of the model neuron when the target or bio neuron spikes.    
            threshOfModelAtBioSpike_array: array of scalars that contain the threshold of the model neuron when the target or bio neuron spikes. 
            NOTE: voltageOfModelAtGridBioSpike_array may be larger than the corresponding values in the threshOfModelAtBioSpike_array because the model
                still runs until the time of the target or bio spike even if the model has already spiked.
            SIGNIFICANT CAVEATS: There are two situatations where the storage of a spike and/or how it should be punished is unclear
                1.  The biological or target spike train does not fire throughout the entire course of the sweep but the model does.
                2.  In the region of stimulus after the last biological spike, the model spikes.
                  In both these situations there are three options.
                    a.  Throw out the data.  It seems like valuable information could be disregarded in this situation.  
                    b.  Insert a virtual reference spike somewhere.  This is nonideal because you don't know where the 
                        real neuron would have spiked and so the weight of you punishment will be incorrect.  However,
                        if this is done at the end of the sweep would be a reasonable choice because if the real neuron were
                        going to produce a spike, it is clearly past the end of the current injection.  However, you don't want
                        to set the virtual spike out to infinity because then the punishment would be disproportionately large 
                        compared to the punishment of other spikes.  The end of the current injection would be another possibility, 
                        however, this is problematic to code since the end of the current injection is not marked.  In the case of the
                        VSD this would not make sense because you would be calculating the voltage at a place where the neuron didn't spike.
                    c.  Set the punishment to some fixed amount that way you can keep track of these episodes.  In this senario you will 
                        the same problems as in b.  However, the added benefit would be that you could track these events for further
                        analysis.  The added drawback is that you would lose the information about how much the spike should be punished.  
                        For example if a model spike occurred at the beginning of the sweep you would think it should be punished more than 
                        at the end of a sweep.
                    Currently I have chosen to do a: throw out all this data    
                '''
        num_spikes = len(spike_train_ids)
             
        # Calculate the time of the target spike in reference to the grid point right before the spike grid point
        grid_times_before_spike = (spike_train_ids - 1) * self.dt
        delta_t_wrt_grid_right_before_spike = interpolated_spike_times - grid_times_before_spike
        
        # if there are no target spikes, just run until the model spikes
        if num_spikes == 0:  
            assert target_spike_exists is False, Exception('Error: target_spike_exists is true, but spike_train_ids has length 0')

            # evaluate the model starting from the beginning until the model spikes
            (voltage_out, threshold_out, AScurrent_matrix_out, grid_spike_time, interpolated_spike_time, yaySpike, voltage_t1, threshold_t1, 
                AScurrents_t1, voltageOfModelAtGridBioSpike, threshOfModelAtGridBioSpike, v_ofModelAtInterpolatedBioSpike, 
                thresh_ofModelAtInterpolatedBioSpike) = self.run_until_spike(voltage_t0, threshold_t0, AScurrents_t0, 
                                                                             stim, 0, len(stim)-1,
                                                                             [], target_spike_exists, self.dt) 

            voltage=voltage_out
            threshold=threshold_out
            AScurrent_matrix=AScurrent_matrix_out

            if len(voltage)!=len(stim):
                warnings.warn('YOUR VOLTAGE OUTPUT IS NOT THE SAME LENGTH AS YOUR STIMULUS')
            if len(threshold)!=len(stim):
                warnings.warn('YOUR THRESHOLD OUTPUT IS NOT THE SAME LENGTH AS YOUR STIMULUS')                
            if len(AScurrent_matrix)!=len(stim):
                warnings.warn('YOUR AScurrent_matrix OUTPUT IS NOT THE SAME LENGTH AS YOUR STIMULUS')
                                          
            #--right now I am not going to keep track of the spikes in the model that spike if the target doesnt spike.
            #--in essence, I am thowing out the cases when the target neuron doesnt spike
            gridISIFromLastTargSpike_array=np.array([])
            interpolatedISIFromLastTargSpike_array=np.array([])
            interpolatedTimeArray=np.array([]) #since there is only one spike it is already in reference to stim start
            interpolatedVoltageArray=np.array([])
            gridTimeArray=np.array([]) #since there is only one spike it is already in reference to stim start
            voltageOfModelAtGridBioSpike_array=np.array([])
            threshOfModelAtGridBioSpike_array=np.array([])
            v_ofModelAtInterpolatedBioSpike_array=np.array([])                
            thresh_ofModelAtInterpolatedBioSpike_array=np.array([])            
        else:
            assert target_spike_exists is True, Exception('There should be a spike in the target')

            # put a zero as the first index because that is where I am going to start counting from.
            #spike_train_ids = np.insert(spike_train_ids,0,0)
            
            # initialize the output arrays
            interpolatedTimeArray=np.empty(num_spikes) #initialize the array
            interpolatedVoltageArray=np.empty(num_spikes)
            gridTimeArray=np.empty(num_spikes)
            gridISIFromLastTargSpike_array=np.empty(num_spikes)
            interpolatedISIFromLastTargSpike_array=np.empty(num_spikes)
            voltageOfModelAtGridBioSpike_array=np.empty(num_spikes)
            threshOfModelAtGridBioSpike_array=np.empty(num_spikes)
            v_ofModelAtInterpolatedBioSpike_array=np.empty(num_spikes)
            thresh_ofModelAtInterpolatedBioSpike_array=np.empty(num_spikes)
            spikeIndStart=0
    
            #Question: because real spikes actually have a width should I be adding some amount of time before I start calculating again?  Basically a biological spike should be considered threshold
            voltage=np.empty(len(stim))
            voltage[:]=np.nan  #TODO: figure out what this is is this numpy or what
            threshold=np.empty(len(stim))
            threshold[:]=np.nan
            AScurrent_matrix=np.empty(shape=(len(stim), len(AScurrents_t0)))
            AScurrent_matrix[:]=np.nan
        
            start_index = 0
            for spike_num in range(num_spikes):
                if spike_num % 10 == 0:
                    logging.info("spike %d / %d" % (spike_num,  num_spikes))

                end_index = int(spike_train_ids[spike_num])

                (voltage_out, threshold_out, AScurrent_matrix_out, grid_spike_time, interpolated_spike_time, yaySpike, voltage_t1, 
                 threshold_t1, AScurrents_t1, voltageOfModelAtGridBioSpike, threshOfModelAtGridBioSpike, v_ofModelAtInterpolatedBioSpike, 
                 thresh_ofModelAtInterpolatedBioSpike)=self.run_until_spike(voltage_t0, threshold_t0, AScurrents_t0, 
                                                                            stim, start_index, end_index,
                                                                            spike_train_ids, target_spike_exists, int(delta_t_wrt_grid_right_before_spike[spike_num]))  

                voltage[start_index:end_index] = voltage_out
                threshold[start_index:end_index] = threshold_out
                AScurrent_matrix[start_index:end_index,:] = AScurrent_matrix_out

                gridISIFromLastTargSpike_array[spike_num] = grid_spike_time
                interpolatedISIFromLastTargSpike_array[spike_num] = interpolated_spike_time
                interpolatedTimeArray[spike_num] = interpolated_spike_time+(start_index)*self.dt #since there is only one spike it is already in reference to stim start
                gridTimeArray[spike_num] = grid_spike_time+(start_index)*self.dt #since there is only one spike it is already in reference to stim start
                voltageOfModelAtGridBioSpike_array[spike_num] = voltageOfModelAtGridBioSpike
                threshOfModelAtGridBioSpike_array[spike_num] = threshOfModelAtGridBioSpike
                v_ofModelAtInterpolatedBioSpike_array[spike_num] = v_ofModelAtInterpolatedBioSpike               
                thresh_ofModelAtInterpolatedBioSpike_array[spike_num] = thresh_ofModelAtInterpolatedBioSpike                

                voltage_t0 = voltage_t1
                threshold_t0 = threshold_t1
                AScurrents_t0 = AScurrents_t1

                start_index = end_index
                
#                if spike_num==1:
#                    AScurrent_matrix[spike_num,:]=AScurrent_matrix_out #initializing the matrix
#                else:
#                    AScurrent_matrix=append(AScurrent_matrix, AScurrent_matrix_out, axis=0)
#                            
            #--get the voltage of the last part of the stim sweep after the last biological spike
            #--currently I am throwing out the data (I am not recording spike times etc) if the model spikes in this time perion  
            (voltage_out, threshold_out, AScurrent_matrix_out, grid_spike_time, interpolated_spike_time, yaySpike, voltage_t1, threshold_t1, \
                AScurrents_t1, voltageOfModelAtGridBioSpike, threshOfModelAtGridBioSpike, v_ofModelAtInterpolatedBioSpike, thresh_ofModelAtInterpolatedBioSpike)= \
                self.run_until_spike(voltage_t0, threshold_t0, AScurrents_t0, 
                                     stim, spike_train_ids[-1].astype(int), len(stim),
                                     spike_train_ids, target_spike_exists, self.dt) #there is no end spike so don't put in a spike

            voltage[spike_train_ids[-1]:]=voltage_out
            threshold[spike_train_ids[-1]:]=threshold_out
            AScurrent_matrix[spike_train_ids[-1]:,:]=AScurrent_matrix_out


        #---some simple error function to make sure things are working. 
        if np.any(np.isnan(voltage)):
            logging.error(self)
            logging.error('voltage indices that are NAN: %s' % np.where(np.isnan(voltage)))
            logging.error('spike indices: %s' % spike_train_ids)
            raise Exception('The voltage vector has not been filled to the length of the stimulus')
        if np.any(np.isnan(threshold)):
            logging.error(self)
            logging.error('threshold indices that are NAN: %s' % np.where(np.isnan(threshold)))
            logging.error('spike indices' % spike_train_ids)
            raise Exception('The threshold vector has not been filled to the length of the stimulus')         
        if np.any(np.isnan(AScurrent_matrix)):
            raise Exception('Your after-spike current vector has not been filled to the length of the stimulus')


        #--the following error functions only work in the case where I am thowing out the sets of data where the target doesnt spike
        if len(interpolatedTimeArray)!=num_spikes or len(interpolatedVoltageArray)!=num_spikes or len(gridTimeArray)!=num_spikes or \
            len(gridISIFromLastTargSpike_array)!=num_spikes or len( interpolatedISIFromLastTargSpike_array)!=num_spikes or \
            len(voltageOfModelAtGridBioSpike_array)!=num_spikes or len(threshOfModelAtGridBioSpike_array)!=num_spikes or \
            len(v_ofModelAtInterpolatedBioSpike_array)!=num_spikes or len(thresh_ofModelAtInterpolatedBioSpike_array)!=num_spikes:
            raise Exception('The number of spikes in your output does not match your target')
            
        return voltage, threshold, AScurrent_matrix, gridTimeArray, interpolatedTimeArray, gridISIFromLastTargSpike_array, interpolatedISIFromLastTargSpike_array, voltageOfModelAtGridBioSpike_array, threshOfModelAtGridBioSpike_array, v_ofModelAtInterpolatedBioSpike_array, thresh_ofModelAtInterpolatedBioSpike_array
                
    def run_until_spike(self, voltage_t0, threshold_t0, AScurrents_t0, 
                        stim, start_index, end_index, 
                        spike_time_steps, target_spike_exists, delta_t_wrt_grid_right_before_spike):
        '''
        Runs the Mihalas Nieber GLIF model for the stimulus input until the step max is reached
        Inputs:
            stepMax: scalar number of indices before a spike has to happen or it is then forced. depreciated 5-22
            voltage_t0(scalar): voltage at beginning of simulation 
            threshold_t0(scalar): threshold for a spike at the beginning of the simulation. 
            init_AScurrent (array):  values of after spike currents at the beginning of the simulation
            NOTE: most of the time these values should be set interpolated_spike_voltage_list, interpolated_spike_threshold_list to the reset values as most the time
              this function is called it will be in the middle of a spike train so it is actually starting
              from the values that are set right after a spike
            stim (array): currently this is part of stimulus array starting somewhere in the middle.  This stimulus 
                array must be the length you want the stimulus to run until. 
            target_spike_exists: True or False value.  If there is only one spike in spike_train_ids, True denotes that this was a real spike,
                False means that the spike was inserted at the end of the current injection for reference error calculations.  
            delta_t_wrt_grid_right_before_spike: this is the time between the spike time and the time of the previous grid point.  This
                is used to calculate the voltage at the interpolated time.  It is needed because you calculate the voltage between the
                two grid points and multiply by this value. This should be set to dt the spike happens at the grid point.
        Outputs:
            voltage_out (array of scalars): voltage trace of neuron.
            grid_spike_time (scalar): time of spike on the time grid. NOTE t
                 
                #need to have it return the values at 34000 but not do a reset
                
            gridISIFromLastTargSpike_array=append(gridISIFromLastTargSpike_array, grid_spike_time)
            interpolatedISIFromLastTargSpike_array=append(interpolatedISIFromLastTargSpike_array, interpolated_spike_time)
            interpolatedTimeArray=append(interpolatedTimeArray, interpolated_spike_time) #since there is only one spike it is already in reference to stim start
            gridTimeArray=append(gridTimeArray, grid_spike_time) #since there is only one spike it is already in reference to stim start
            voltageOfModelAtGridBioSpike_array=append(voltageOfModelAtGridBioSpike_array, voltageOfModelAtGridBioSpike)
            threshOfModelAtGridBioSpike_array=append(threshOfModelhis is in reference t=0 at the start of this function. 
            interpolated_spike_time (scalar): interpolated or extrapolated actual time of a spike. NOTE this is in reference t=0 at the
                 start of this function. 
            yaySpike (logical): True if there was a spike within the allotted time.  False if the spike needed to be forced.
            voltage_t0  (scalar): voltage after the natural orinterpolated_spike_voltage_list, interpolated_spike_threshold_list forced spike
            threshold_t0 (scalar): threshold after the natural or forced spike
            AScurrents_t0 (vector of scalars): amplitude of spike induced currents after the natural or forced spike
            voltage_t1 (scalar): value of voltage of neuron at last step (when the bio neuron spikes)
            threshold_t1 (scalar: value of threshold at the last step (when the bio neuron spikes
        '''
#        def return_false_s():
#            return False
#        return_false = autojit(return_false_s)
#        yaySpike = return_false() #initialize value

        #making copies just to make sure this thing is doing pass by reference    
        
        AScurrents_t0 = np.copy(AScurrents_t0)

        #--preallocate arrays and matricies
        num_time_steps= end_index - start_index

        voltage_out=np.empty(num_time_steps)
        voltage_out[:]=np.nan
        threshold_out=np.empty(num_time_steps)
        threshold_out[:]=np.nan
        AScurrent_matrix=np.empty(shape=(num_time_steps, len(AScurrents_t0)))
        AScurrent_matrix[:]=np.nan

        grid_spike_time = None
        interpolated_spike_time = None
        
        #--calculate the model values between the two target spikes (don't stop if there is a spike)
        for time_step in xrange(num_time_steps):
            #Note that here you are not recording the first v0 because that was recoded at the end of the previous spike
            voltage_out[time_step]=voltage_t0 
            threshold_out[time_step]=threshold_t0
            AScurrent_matrix[time_step,:]=np.matrix(AScurrents_t0) 
            
            if np.isnan(voltage_t0) or np.isinf(voltage_t0) or np.isnan(threshold_t0) or np.isinf(threshold_t0) or any(np.isnan(AScurrents_t0)) or any(np.isinf(AScurrents_t0)):
                logging.error(self)
                logging.error('time step: %d / %d' % (time_step, num_time_steps))
                logging.error('    voltage_t0: %f' % voltage_t0)
                logging.error('    voltage started the run at: %f' % voltage_out[0])
                logging.error('    voltage before: %s' % voltage_out[time_step-20:time_step])
                logging.error('    threshold_t0: %f' % threshold_t0)
                logging.error('    threshold started the run at: %f' % threshold_out[0])
                logging.error('    threshold before: %s' % threshold_out[time_step-20:time_step])
                logging.error('    AScurrents_t0: %s' % AScurrents_t0)
                raise Exception('Invalid threshold, voltage, or after-spike current encountered.')
            
            (voltage_t1, threshold_t1, AScurrents_t1) = self.dynamics(voltage_t0, threshold_t0, AScurrents_t0, stim[time_step+start_index], time_step+start_index, spike_time_steps) #TODO fix list versus array
            
            voltage_t0=voltage_t1
            threshold_t0=threshold_t1
            AScurrents_t0=AScurrents_t1
            
        #figuring out whether model neuron spiked or not        
        for time_step in range(0, num_time_steps): 
            if voltage_out[time_step]>threshold_out[time_step]:
                grid_spike_time=self.dt*time_step #not that this should be time_step even though it is index+1 in runModel function because here it isnt recorded until the next step
                interpolated_spike_time=self.dt*((time_step-1)+(threshold_out[time_step-1]-voltage_out[time_step-1])/(voltage_out[time_step]-threshold_out[time_step]-voltage_out[time_step-1]+threshold_out[time_step-1])) 
                break
                
        # if the last voltage is above threshold and there hasen't already been a spike
        if voltage_t0 > threshold_out[-1] and grid_spike_time is None: 
            grid_spike_time = self.dt*num_time_steps
            interpolated_spike_time=self.dt*((num_time_steps-1)+(threshold_out[num_time_steps-1]-voltage_out[num_time_steps-1])/(voltage_t0-threshold_t0-voltage_out[num_time_steps-1]+threshold_out[num_time_steps-1])) 
                        
        # if the target spiked, reseting at the end so that next round will start at reset but not recording it in the voltage here.
        if target_spike_exists: 
            (voltage_t0, threshold_t0, AScurrents_t0)=self.reset(voltage_t1, threshold_t1, AScurrents_t1, time_step) #reset the variables

        #if the model never spiked, extrapolate to guess when it would have spiked
        if grid_spike_time is None: 
            # formula is self.dt*(num_time_steps)/(1-(threshold_t1-voltage_t1)/(threshold_t0-voltage_t0))
            interpolated_spike_time = self.dt*(num_time_steps)/(1-(threshold_t1-voltage_t1)/(threshold_t0-voltage_t0)) 
            grid_spike_time = np.ceil(interpolated_spike_time/self.dt)*self.dt  #grid spike time based off extrapolated spike time (changed floor to ceil 5-13-13
        
        v_ofModelAtInterpolatedBioSpike = voltage_out[-1]+delta_t_wrt_grid_right_before_spike*(voltage_t1-voltage_out[-1])/self.dt
        thresh_ofModelAtInterpolatedBioSpike = threshold_out[-1]+delta_t_wrt_grid_right_before_spike*(threshold_t1-threshold_out[-1])/self.dt
        
        return voltage_out, threshold_out, AScurrent_matrix, \
            grid_spike_time, interpolated_spike_time, grid_spike_time is not None, \
            voltage_t0, threshold_t0, AScurrents_t0, voltage_t1, threshold_t1, \
            v_ofModelAtInterpolatedBioSpike, thresh_ofModelAtInterpolatedBioSpike 


    

