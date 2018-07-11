from __future__ import absolute_import
from __future__ import print_function

import os
import shutil
import math
import numpy
import collections
import pylab as pl
import matplotlib
import time
try:
    import cPickle as pickle
except:
    import pickle

from . import datacontainer
from . import paramcontainer
from . import mfista
from . import cv

class SparseModelingImager(object):
    """
    Core implementation of sparse modeling specialized for ALMA.
    It performs visibility gridding on uv-plane.
    """
    
    @property
    def griddedvis(self):
        """
        TODO
        """
        return getattr(self, '_griddedvis', None)
    
    @griddedvis.setter
    def griddedvis(self, value):
        if value is None:
            self._griddedvis = None
        elif type(value) == datacontainer.GriddedVisibilityStorage:
            self._griddedvis = value
        else:
            raise TypeError('Given value is not an instance of GriddedVisibilityStorage')
        
    @property
    def imagearray(self):
        """
        TODO
        """
        return getattr(self, '_imagearray', None)
    
    @imagearray.setter
    def imagearray(self, value):
        if value is None:
            self._imagearray = None
        elif type(value) == datacontainer.ResultingImageStorage:
            self._imagearray = value
        else:
            raise TypeError('Given value is not an instance of ResultingImageStorage')
        
    @property
    def uvgridconfig(self):
        """
        TODO
        """
        return getattr(self, '_uvgridconfig', None)
    
    @uvgridconfig.setter
    def uvgridconfig(self, value):
        if value is None:
            self._uvgridconfig = None
        elif type(value) == datacontainer.UVGridConfig:
            self._uvgridconfig = value
        else:
            raise TypeError('Given value is not an instance of UVGridConfig')
    
    @property
    def imagesuffix(self):
        """
        Suffix for the exported image. Default is 'pickle' since the export format is 
        Python's cPickle object. Suffix can be customized depending on how to override 
        exportimage method.
        """
        return 'pickle'
    
    def __init__(self, solver_name='sparseimaging'):
        """
        Constructor
        
        Parameters:
            solver_name    name of the solver. currently only 'sparseimaging' is supported.
                      (default 'sparseimaging' ---> sparse imaging library written by S. Ikeda)
       """
        self.solver_name = solver_name
        self.__initialize()
    
    def __initialize(self):
        # configuration
        self.imparam = None
        self.visparams = []
        
        # working array
        self.griddedvis = None
        self.imagearray = None
        
        # TODO: optimize number of threads
        self.num_threads = 2
        
        # create MFISTA instance with dummy parameter
        mfistaparam = paramcontainer.MfistaParamContainer(l1=0.0, ltsv=0.0)
        solver_cls = mfista.SolverFactory(self.solver_name)
        self.solver = solver_cls(mfistaparam)
    
    def mfista(self, l1, ltsv, maxiter=50000, eps=1.0e-5, clean_box=None, 
               storeinitialimage=True, overwriteinitialimage=False):
        """
        Run MFISTA algorithm on gridded visibility data.
        gridvis must be executed beforehand.
        
        Parameters:
            l1 -- L1 regularization term
            ltsv -- TSV regularization term
            maxiter -- maximum number of iteration for MFISTA
            eps -- threshold factor for MFISTA
            clean_box -- clean box as a float array
            storeinitialimage -- keep the result as an initial image for next run
            overwriteinitialimage -- overwrite existing initial image
        """
        self.mfistaparam = paramcontainer.MfistaParamContainer(l1=l1, ltsv=ltsv,
                                                               maxiter=maxiter, eps=eps,
                                                               clean_box=clean_box)
        arr = self._mfista(self.mfistaparam, self.griddedvis,
                           storeinitialimage=storeinitialimage, overwriteinitialimage=overwriteinitialimage)
        self.imagearray = datacontainer.ResultingImageStorage(arr)
    
    def _mfista(self, mfistaparam, griddedvis, storeinitialimage=True, overwriteinitialimage=False):
        assert griddedvis is not None
        self.solver.mfistaparam = mfistaparam
        return self.solver.solve(griddedvis, storeinitialimage, overwriteinitialimage)
    
    def exportimage(self, imagename, overwrite=False):
        """
        Export MFISTA result as a cPickle object.
        mfista must be executed beforehand.
         
        Parameters:
            imagename  name of output image name
        """
        if self.imagearray is None:
            raise RuntimeError('You don\'t have an image array!')
        
        if os.path.exists(imagename) and overwrite == False:
            raise RuntimeError('Cannot overwrite existing file "{}"'.format(imagename))
        
        with open(imagename, 'w') as f:
            pickle.dump(self.imagearray, f)

    def getimage(self, imagename):
        """
        Get image data from exported file
        
        Parameters:
            imagename  name of image to be read
        """
        if not os.path.exists(imagename):
            raise RuntimeError('image "{}" does not exist'.format(imagename))
        
        with open(imagename, 'rb') as f:
            data = pickle.load(f)
            
        return data

    def cvforgridvis(self, l1_list, ltsv_list, num_fold=10, imageprefix='image', imagepolicy='full', 
               summarize=True, figfile=None, datafile=None, maxiter=50000, eps=1.0e-5, clean_box=None):
        """
        Perform cross validation and search the best parameter for L1 and Ltsv from 
        the given list of these.
        
        Inputs:
            l1_list -- list of L1 values to examine
            ltsv_list -- List of Ltsv values to examine
            num_fold -- number of visibility subsets for cross validation
            imageprefix -- prefix for output image
                           imageprefix is used for the best image (<imageprefix>.fits) 
            imagepolicy -- policy of output image ('full' or 'best')
                           full: keep all FITS image produced by cross validation
                           best: only keep FITS image corersponding to the best solution
            summarize -- generate summary plot if True
            figfile -- name of summary figure of cross validation. 
                       None will not produce a file.
            datafile -- name of output data file containing whole MSE values. 
                        None will not produce a file.
            maxiter -- maximum number of iteration for MFISTA algorithm
            eps -- threshold factor for MFISTA algorithm
            clean_box -- clean box as a float array (default None)
        
        Output:
            dictionary containing best L1 (key: L1), best Ltsv (key;Ltsv), and
            corresponding image name (key: image, should be <imageprefix>.fits)
        """
        start_time = time.time()
        
        # sanity check
        if imagepolicy not in ('best', 'full'):
            raise ArgumentError('imagepolicy must be best or full. {0} was provided.'.format(imagepolicy))
        
        try:
            np_l1_list = numpy.asarray(l1_list)
            np_ltsv_list = numpy.asarray(ltsv_list)
        except Exception, e:
            print('Exception occurred')
            print(str(e))
            raise ArgumentError('l1_list or ltsv_list (or both) seems invalid.')
        
        if str(np_l1_list.dtype) == 'object':
            raise ArgumentError('l1_list contains invalid value')
        if str(np_ltsv_list.dtype) == 'object':
            raise ArgumentError('ltsv_list contains invalid value')
        
        result_L1 = []
        result_Ltsv = []
        result_mse = []
        result_image = []
        
        num_L1 = len(np_l1_list)
        num_Ltsv = len(np_ltsv_list)
        L1_sort_index = numpy.argsort(np_l1_list)
        Ltsv_sort_index = numpy.argsort(np_ltsv_list)
        
        sorted_l1_list = np_l1_list[L1_sort_index]
        sorted_ltsv_list = np_ltsv_list[Ltsv_sort_index]
        
        if summarize is True:
            PlotterClass = CVPlotter
        else:
            PlotterClass = NullPlotter
        plotter = PlotterClass(num_L1, num_Ltsv, sorted_l1_list, sorted_ltsv_list)
            
        if datafile is not None:
            f = open('cvresult.dat', 'w')
        else:
            f = open(os.devnull, 'w')
        print('# L1, Ltsv, MSE', file=f)
        
        # initialize CV
        self.initializecv(num_fold=num_fold)
                
        #for j, Ltsv in enumerate(np_ltsv_list):
        # loop Ltsv in ascending order
        for j in xrange(num_Ltsv):
            Ltsv = sorted_ltsv_list[j]
            # trick to update initial image when Ltsv is changed
            overwrite_initial = True
            
            #for i, L1 in enumerate(np_l1_list):
            # loop L1 in descending order
            for i in xrange(num_L1 - 1, -1, -1):
                L1 = sorted_l1_list[i]
                result_L1.append(L1)
                result_Ltsv.append(Ltsv)
                
                # get full visibility image first
                imagename = 'L1_{0}_Ltsv_{1}.{2}'.format(int(math.log10(L1)), int(math.log10(Ltsv)),
                                                         self.imagesuffix)
                self.mfista(L1, Ltsv, maxiter=maxiter, eps=eps, clean_box=clean_box,
                            storeinitialimage=True, overwriteinitialimage=overwrite_initial)
                self.exportimage(imagename, overwrite=True)
                result_image.append(imagename)
                
                # then evaluate MSE
                mse = self.computegridmse(L1, Ltsv, maxiter, eps, clean_box)
                result_mse.append(mse)
                
                print('L1 10^{0} Ltsv 10^{1}: MSE {2} FITS {3}'.format(int(math.log10(L1)),
                                                                       int(math.log10(Ltsv)),
                                                                       mse,
                                                                       imagename))
                print('{0}, {1}, {2}'.format(L1, Ltsv, mse), file=f)
        
                if summarize is True:
                    imagearray = self.getimage(imagename)
                    data = numpy.squeeze(imagearray.data) #data will be 2D
                    plotter.plotimage(i, j, data, mse)
                    
                # As long as Ltsv is kept, initial image will not be updated
                #overwrite_initial = False
                            
        # finalize CV
        self.finalizecv()
        
        f.close()
        
        best_solution = numpy.argmin(result_mse)
        best_mse = result_mse[best_solution]
        best_image = result_image[best_solution]
        best_L1 = result_L1[best_solution]
        best_Ltsv = result_Ltsv[best_solution]
        
#         L1_index = np_l1_list.tolist().index(best_L1)
#         Ltsv_index = np_ltsv_list.tolist().index(best_Ltsv)
        L1_index = numpy.where(sorted_l1_list == best_L1)[0][0]
        Ltsv_index = numpy.where(sorted_ltsv_list == best_Ltsv)[0][0]
        if best_mse >= 0.0:
            plotter.mark_bestimage(L1_index, Ltsv_index)
        
        plotter.draw()
        if figfile is not None:
            plotter.savefig(figfile)
        # completed
        end_time = time.time()
        
        if best_mse >= 0.0:
            print('Process completed. Optimal result is as follows')
            print('    L1, Ltsv = 10^{0}, 10^{1}'.format(int(math.log10(best_L1)), int(math.log10(best_Ltsv))))
            print('    MSE = {0}'.format(best_mse))
            print('    imagename = {0}'.format(best_image))
        else:
            print('Process completed. Cross-validation was not performed.')
            print('WARNING: Optimal solution will not be correct one since no CV was executed.')
        
        print('Elapsed {0} sec'.format(end_time - start_time))
        
        
        # copy the best image to final image
        shutil.copy2(best_image, imageprefix+'.'+self.imagesuffix)
        if imagepolicy == 'full':
            # keep all intermediate images
            pass
        elif imagepolicy == 'best':
            # remove all intermediate images
            for imagename in result_image:
                os.remove(imagename)
        else:
            assert False
            
        # finally, return best L1 and Ltsv
        return {'L1': best_L1, 'Ltsv': best_Ltsv}
           

    def initializecv(self, num_fold=10):
        assert self.griddedvis is not None
        
        if (not hasattr(self, 'visset')) or self.visset is None:
            self.visset = cv.VisibilitySubsetGenerator(self.griddedvis, num_fold) 
    
    def finalizecv(self):
        self.visset = None
    
    def computegridmse(self, l1, ltsv, maxiter=50000, eps=1.0e-5, clean_box=None):
        """
        Compute mean-square-error (MSE) on resulting image.
        MSE is evaluated from gridded visibility.
        """
        mfistaparam = paramcontainer.MfistaParamContainer(l1=l1, ltsv=ltsv,
                                                          maxiter=maxiter, eps=eps, 
                                                          clean_box=clean_box)
        assert self.griddedvis is not None
        
        evaluator = cv.MeanSquareErrorEvaluator()
        num_fold = self.visset.num_fold
        
        if num_fold <= 1:
            # CV is disabled
            return -1.0
        
        subset_handler = cv.GriddedVisibilitySubsetHandler(self.visset, 
                                                             self.uvgridconfig)
        
        for i in xrange(num_fold):
            # pick up subset for cross validation
            with subset_handler.generate_subset(subset_id=i) as subset:
            
                # run MFISTA
                imagearray = self._mfista(mfistaparam, 
                                          subset.visibility_active,
                                          False, False)

                # evaluate MSE (Mean Square Error)
                mse = evaluator.evaluate_and_accumulate(subset.visibility_cache, 
                                                        imagearray,
                                                        self.uvgridconfig)
             
        mean_mse = evaluator.get_mean_mse()
        
        return mean_mse
    
    def computemse(self, num_fold=10):
        """
        Compute mean-square-error (MSE) on resulting image.
        MSE is evaluated from raw visibility (i.e., prior to gridding).
        """
        raise NotImplementedError('Computation of MSE from raw visibility is future development.')
#         assert self.griddedvis is not None
#         
#         evaluator = core.MeanSquareErrorEvaluator()
#         visgridder = core.CrossValidationVisibilityGridder(self.gridparam, 
#                                                            self.imparam, 
#                                                            self.griddedvis.num_ws,
#                                                            num_fold)
#         
#         for i in xrange(num_fold):
#             for visparam in self.visparam:
#                 reader = VisibilityReader(visparam)
#                 converter = VisibilityConverter(visparam, self.imparam)
#                 for working_set in sakura.paraMap(self.num_threads, 
#                                            converter.generate_working_set, 
#                                            reader.readvis()):
#                     visgridder.grid(working_set, i)
#             griddedvis = visgridder.get_result()
#             visibility_cache = visgridder.get_visibility_cache()
#             
#             # run MFISTA
#             imagearray = self._mfista(self.mfistaparam,
#                                       griddedvis)
#             
#             # evaluate MSE (Mean Square Error)
#             mse = evaluator.evaluate_and_accumulate(visibility_cache,
#                                                     imagearray)
#             
#         mean_mse = evaluator.get_mean_mse()
#         
#         return mean_mse
    
    def computeapproximatemse(self):
        """
        Evaluate approximate mean-square-error (MSE) on resulting image.
        """
        raise NotImplementedError('Computation of Approximate MSE (LOOE) is not implemented yet.')
#         assert self.griddedvis is not None
#         evaluator = core.ApproximateCrossValidationEvaluator()
#         
#         acv = evaluator.evaluate(self.griddedvis)
#         return 0.0


class CVPlotter(object):
    def __init__(self, nv, nh, L1_list, Ltsv_list):
        self.nh = nh
        self.nv = nv

        self.left_margin = 0.1
        self.right_margin = 0.1
        self.bottom_margin = 0.1
        self.top_margin = 0.1
        total_width = 1.0 - (self.left_margin + self.right_margin)
        total_height = 1.0 - (self.bottom_margin + self.top_margin)
        dx = total_width / float(self.nh)
        dy = total_height / float(self.nv)
        self.dx = min(dx, dy)
        self.dy = self.dx
        f = pl.figure(num='CVPlot', figsize=(8,8))
        pl.clf()
        left = self.left_margin
        bottom = self.bottom_margin
        height = self.dy * self.nv
        width = self.dx * self.nh
        outer_frame = pl.axes([left, bottom, width, height])
        outer_frame.set_xlim(-0.5, self.nh - 0.5)
        outer_frame.set_ylim(-0.5, self.nv - 0.5)
        outer_frame.set_xlabel('log10(Ltsv)')
        outer_frame.set_ylabel('log10(L1)')
        outer_frame.xaxis.set_major_locator(matplotlib.ticker.FixedLocator(range(self.nh)))
        outer_frame.yaxis.set_major_locator(matplotlib.ticker.FixedLocator(range(self.nv)))
        outer_frame.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, pos: int(math.log10(Ltsv_list[int(x)]))))
        outer_frame.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, pos: int(math.log10(L1_list[int(x)]))))
        
        self.L1_list = L1_list
        self.Ltsv_list = Ltsv_list
        
        self.axes_list = collections.defaultdict(dict)
        
    def plotimage(self, row, column, data, mse):
        left = self.left_margin + column * self.dx
        bottom = self.bottom_margin + row * self.dy
        height = self.dx
        width = self.dy
        #print 'pl.axes([{0}, {1}, {2}, {3}])'.format(left, bottom, width, height)
        nx, ny = data.shape
        a = pl.axes([left, bottom, width, height])
        a.imshow(numpy.flipud(data.transpose()))
        if mse >= 0.0:
            a.text(nx-2, 5, '{:.5g}'.format(mse), ha='right', va='top', fontdict={'size': 'small', 'color': 'white'})
        a.xaxis.set_major_locator(matplotlib.ticker.NullLocator())
        a.yaxis.set_major_locator(matplotlib.ticker.NullLocator())
        self.axes_list[row][column] = a

    def mark_bestimage(self, row, column):
        best_axes = self.axes_list[row][column]
        bbox = best_axes.get_position()
        best_frame = pl.axes(bbox, axisbg='none')
        best_frame.xaxis.set_major_locator(matplotlib.ticker.NullLocator())
        best_frame.yaxis.set_major_locator(matplotlib.ticker.NullLocator())
        for loc, spine in best_frame.spines.items():
            spine.set_color('red')
            spine.set_linewidth(3)
            
    def draw(self):
        pl.draw()
        
    def savefig(self, figfile):
        pl.savefig(figfile)

        
class NullPlotter(object):
    def __init__(self, *args, **kwargs):
        pass
    
    def plotimage(self, *args, **kwargs):
        pass
        
    def mark_bestimage(self, *args, **kwargs):
        pass

    def draw(self, *args, **kwargs):
        pass
        
    def savefig(self, *args, **kwargs):
        pass
    
